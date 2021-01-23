import json
import discord
from discord.ext import commands
import asyncio

intents = discord.Intents.default()

DEFAULT_EMBED_COLOR = 0xFFA500
ERROR_EMBED_COLOR = 0xFF6347
BUG_EMBED_COLOR = 0x5058a8
MESSAGE_MAX_LEN = 2000
DEFAULT_PREFIX = "!"
PREFIX_JSON = "guild_prefixes.json"


def get_prefix(bot, message):
    if message.channel.type is not discord.ChannelType.private:
        with open(PREFIX_JSON, 'r') as f:
            prefixes = json.load(f)
            if str(message.guild.id) not in prefixes:
                prefixes[str(message.guild.id)] = DEFAULT_PREFIX
            pf = prefixes[str(message.guild.id)]
    else:
        pf = DEFAULT_PREFIX
    return pf


client = discord.Client()
bot = commands.Bot(command_prefix=get_prefix, help_command=None)

waiting_users = []


@bot.event
async def on_guild_join(guild): #when the bot joins the guild
    with open(PREFIX_JSON, 'r') as f:
        prefixes = json.load(f)

    prefixes[str(guild.id)] = DEFAULT_PREFIX

    with open(PREFIX_JSON, 'w') as f:
        json.dump(prefixes, f, indent=4)


@bot.event
async def on_guild_remove(guild):
    with open(PREFIX_JSON, 'r') as f:
        prefixes = json.load(f)

    if str(guild.id) in prefixes:
        prefixes.pop(str(guild.id))

    with open(PREFIX_JSON, 'w') as f:
        json.dump(prefixes, f, indent=4)


async def changeprefix(guild_id, prefix):
    with open(PREFIX_JSON, 'r') as f:
        prefixes = json.load(f)

    prefixes[str(guild_id)] = prefix

    with open(PREFIX_JSON, 'w') as f:
        json.dump(prefixes, f, indent=4)

    return True


@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=DEFAULT_PREFIX+"help"))
    print(f'{bot.user} has connected to Discord!')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return await send_error(ctx, str(error)+"!")
    pass


async def is_already_waiting(sender, receiver):
    return (sender.id, receiver.id) in waiting_users


async def wait_for_reaction(sender, receiver, timeout, check):
    waiting_users.append((sender.id, receiver.id))
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=timeout, check=check)
    except asyncio.TimeoutError as e:
        raise e
    finally:
        waiting_users.remove((sender.id, receiver.id))
    return reaction, user


async def send_message(context, msg_text):
    msg_embed = discord.Embed(description=msg_text,
                              color=DEFAULT_EMBED_COLOR)
    return await context.send(embed=msg_embed)


async def send_embed(context, description, footer="", color=DEFAULT_EMBED_COLOR, fields={}, title=""):
    msg_embed = discord.Embed(description=description,
                              title=title,
                              color=color)
    if footer:
        msg_embed.set_footer(text=footer)

    if fields:
        for key in fields:
            msg_embed.add_field(name=key, value=fields[key])
    return await context.send(embed=msg_embed)


async def send_error(context, msg_text):
    msg_embed = discord.Embed(description=msg_text,
                              color=ERROR_EMBED_COLOR)
    return await context.send(embed=msg_embed)


async def find_user(user_id):
    if isinstance(user_id, int):
        return bot.get_user(user_id)
    else:
        return None
