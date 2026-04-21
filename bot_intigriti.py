import discord
from discord.ext import commands, tasks
import requests
import json
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# Carrega as variáveis do arquivo .env (quando rodando localmente)
load_dotenv()

# ================= CONFIGURAÇÕES =================
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
INTIGRITI_TOKEN = os.getenv('INTIGRITI_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

# ... o resto do código continua igualzinho ...

# Endpoints da Intigriti (Baseados na documentação v1)
API_BASE = "https://api.intigriti.com/external/researcher/v1"
HEADERS = {
    "Authorization": f"Bearer {INTIGRITI_TOKEN}",
    "Accept": "application/json"
}

# Arquivos locais para manter o estado (banco de dados simples)
STATE_FILE = 'intigriti_state.json'

# Inicializando estado
if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, 'w') as f:
        json.dump({"known_programs": [], "tracked_suspended": []}, f)

def carregar_estado():
    with open(STATE_FILE, 'r') as f:
        return json.load(f)

def salvar_estado(estado):
    with open(STATE_FILE, 'w') as f:
        json.dump(estado, f, indent=4)

# Configurando o Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ================= LÓGICA DE API =================
def buscar_programas():
    try:
        # A API retorna os programas. Precisamos lidar com paginação se houver muitos, 
        # mas para o básico, uma requisição GET resolve.
        response = requests.get(f"{API_BASE}/programs", headers=HEADERS)
        response.raise_for_status()
        return response.json() # Retorna a lista de programas
    except Exception as e:
        print(f"Erro ao buscar API da Intigriti: {e}")
        return []

# ================= LOOP DE MONITORAMENTO =================
@tasks.loop(minutes=15) # Roda a cada 15 minutos (não seja muito agressivo no rate limit)
async def monitorar_intigriti():
    canal = bot.get_channel(CHANNEL_ID)
    if not canal:
        return

    estado = carregar_estado()
    programas = buscar_programas()
    
    if not programas:
        return

    novos_conhecidos = estado["known_programs"].copy()
    
    for prog in programas:
        prog_id = prog.get('id')
        prog_name = prog.get('name', 'Desconhecido')
        prog_status = prog.get('status', 'Unknown').upper() # ACTIVE, SUSPENDED, etc.
        
        # 1. Alerta de NOVO programa (literalmente novo, ID não estava na lista)
        if prog_id not in estado["known_programs"]:
            novos_conhecidos.append(prog_id)
            # Ignora programas já suspensos ou fechados na primeira descoberta para focar em alvos ativos
            if prog_status == 'ACTIVE': 
                embed = discord.Embed(title="🚨 NOVO PROGRAMA NA INTIGRITI!", color=0x00ff00)
                embed.add_field(name="Nome", value=prog_name, inline=False)
                embed.add_field(name="Link", value=f"https://app.intigriti.com/programs/{prog.get('companyHandle')}/{prog.get('handle')}", inline=False)
                await canal.send(embed=embed)

        # 2. Verifica se algum programa rastreado foi reaberto (Unsuspended)
        for tracked in estado["tracked_suspended"]:
            # Compara ignorando case para evitar erros de digitação
            if tracked.lower() in prog_name.lower() or tracked == prog_id:
                if prog_status == 'ACTIVE':
                    embed = discord.Embed(title="🔥 PROGRAMA REABERTO! HORA DE SUBMETER!", color=0xff0000)
                    embed.add_field(name="Nome", value=prog_name, inline=False)
                    embed.add_field(name="Ação", value="O programa saiu do status Suspended e agora está ativo. Envie aquele report!", inline=False)
                    await canal.send(embed=embed)
                    
                    # Remove da lista de rastreio para não ficar avisando toda hora
                    estado["tracked_suspended"].remove(tracked)

    # Atualiza o banco de dados
    estado["known_programs"] = novos_conhecidos
    salvar_estado(estado)

# ================= COMANDOS =================
@bot.command(name='track')
async def track_program(ctx, *, nome_programa: str):
    """Adiciona um programa suspenso para ser monitorado."""
    estado = carregar_estado()
    if nome_programa not in estado["tracked_suspended"]:
        estado["tracked_suspended"].append(nome_programa)
        salvar_estado(estado)
        await ctx.send(f"✅ Rastreamento ativado para: **{nome_programa}**. Vou te avisar assim que o status mudar para ACTIVE.")
    else:
        await ctx.send(f"⚠️ O programa **{nome_programa}** já está sendo rastreado.")

@bot.command(name='list_tracked')
async def list_tracked(ctx):
    """Lista todos os programas que estão sendo aguardados."""
    estado = carregar_estado()
    rastreados = estado.get("tracked_suspended", [])
    if rastreados:
        await ctx.send(f"📋 Monitorando reabertura de: {', '.join(rastreados)}")
    else:
        await ctx.send("Nada sendo monitorado no momento.")

# ================= START =================
@bot.event
async def on_ready():
    print(f'Bot {bot.user} conectado e pronto!')
    # Inicia a task em background assim que o bot conecta
    monitorar_intigriti.start()

bot.run(DISCORD_TOKEN)