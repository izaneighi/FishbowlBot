# bot.py
import os
#import json
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import FishbowlBackend
import datetime
import random
import typing
import traceback
import asyncio
import pandas as pd
import re

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

MAX_USER_SESSIONS = 1
MAX_USERS_PER_SESSION = 99
MAX_TOTAL_SESSIONS = 100
MAX_BOWL_SIZE = 999
CONFIRM_TIME_OUT = 10.0
BG_REFRESH_TIME = 60.0
SESSION_TIMEOUT = datetime.timedelta(days=0, hours=1, seconds=0)
BUG_REPORT_CHANNEL = 796498229872820314
SCRAP_MAX_LEN = 1000
EMBED_DESCRIPTION_LIMIT = 1000
EMBED_FOOTER_LIMIT = 1000

EMOJI_Y = "\N{THUMBS UP SIGN}"
EMOJI_N = "\N{THUMBS DOWN SIGN}"

help_df = pd.read_csv(r"Fishbowl_help.tsv", index_col="Command", sep="\t").fillna('')
help_df["DetailedHelp"] = help_df["DetailedHelp"].str.replace('\\\\n', '\n', regex=True)

sessions = {}
users = {}


class CreatorOnly(commands.CheckFailure):
    pass


class UserNotInSession(commands.CheckFailure):
    pass


class PermissionDenied(commands.CheckFailure):
    pass


class CommandCannotBeDMed(commands.CheckFailure):
    pass


class BadInputCharacter(commands.CheckFailure):
    pass


def check_user_in_session():
    async def predicate(ctx):
        user_id = ctx.author.id
        if user_id not in users:
            raise UserNotInSession()
        return True
    return commands.check(predicate)


def check_creator():
    async def predicate(ctx):
        user_id = ctx.author.id
        session_id = users[user_id]
        if sessions[session_id]['creator'] != user_id:
            raise CreatorOnly()
        return True
    return commands.check(predicate)


def check_permission(admin=False, server_owner=False):
    async def predicate(ctx):
        if admin and not ctx.message.author.guild_permissions.administrator:
            raise PermissionDenied()
        if server_owner and not ctx.message.author.id == ctx.guild.owner_id:
            raise PermissionDenied()
        return True
    return commands.check(predicate)


def check_no_dm():
    async def predicate(ctx):
        if ctx.channel.type is discord.ChannelType.private:
            raise CommandCannotBeDMed()
        return True
    return commands.check(predicate)


async def general_errors(ctx, error):
    if isinstance(error, UserNotInSession):
        return await FishbowlBackend.send_error(ctx, "You are currently not in a session!")
    if isinstance(error, CreatorOnly):
        return await FishbowlBackend.send_error(ctx, "Only the creator of the session can use this command!")
    if isinstance(error, commands.ExpectedClosingQuoteError) or isinstance(error, commands.InvalidEndOfQuotedStringError):
        return await FishbowlBackend.send_error(ctx, str(error))
    if isinstance(error, BadInputCharacter):
        return await FishbowlBackend.send_error(ctx, "No mentions, channels, URLs, or code blocks!")
    await FishbowlBackend.send_error(ctx, "Something unexpected broke!")
    traceback.print_exc()


def clean_session_id(argument):
    return argument.lower().strip()


def clean_arg(argument):
    return argument.lower().strip()


def session_update_time(session_id):
    sessions[session_id]['last_modified'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return


def user_to_readable(user):
    return "%s#%s" % (user.name, user.discriminator)


def clean_scrap(scrap_str):
    return scrap_str.strip().rstrip(",")


def check_scrap(scrap_str):
    try:
        s = int(scrap_str)
        if s:
            return "Sorry, I don't accept integers as scraps! (Try writing out the number or wrapping it in single quotes instead!)"
    except ValueError:
        pass
    if re.search(r"^<@!\d{18}>", scrap_str):
        return "User mentions are not allowed as scraps!"
    if re.search(r"^<#\d{18}>", scrap_str):
        return "Channel mentions are not allowed as scraps!"
    #is_link = re.search(r"((http|ftp|https)://)?([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?",
    #                    scrap_str)
    if re.search("`", scrap_str):
        return "Code blocks are not allowed as scraps!"
    return ""


async def get_user_session(ctx, user_id):
    if user_id not in users:
        await FishbowlBackend.send_error(ctx, "%s is currently not in a session!" % ctx.author.mention)
        return None
    session_id = users[user_id]
    return session_id


async def username_session_lookup(session_id, username):
    if session_id not in sessions:
        return None

    try:
        username, discrim = username.split("#")
    except ValueError:
        return None

    all_players = [await FishbowlBackend.find_user(user_id) for user_id in sessions[session_id]['players'].keys()]
    player_match = next((player for player in all_players if player.name == username and player.discriminator == discrim),
                        None)
    return player_match


def reaction_check(message=None, emoji=None, author=None, ignore_bot=True):
    message_id = message.id

    def check(reaction, user):
        if ignore_bot and user.bot:
            return False
        if message and reaction.message.id != message_id:
            return False
        if emoji and reaction.emoji not in emoji:
            return False
        if author and user.id != author.id:
            return False
        return True
    return check


@tasks.loop(seconds=BG_REFRESH_TIME)
async def clean_inactive_sessions():
    check_time = datetime.datetime.now()
    inactive_sess = [key for key in sessions if
                     (check_time - datetime.datetime.strptime(sessions[key]["last_modified"], '%Y-%m-%d %H:%M:%S')) > SESSION_TIMEOUT]
    for key in inactive_sess:
        print('Clearing Session #%s for inactivity...' % key)
        user_list = sessions[key]['players'].keys()
        for user_id in user_list:
            msg = "Session #%s has been closed due to inactivity!" % key
            if user_id == sessions[key]['creator']:
                msg += "\nNext time, make sure to close the session once you're done with `end`!"
            dm_ctx = await FishbowlBackend.find_user(user_id)
            await FishbowlBackend.send_message(dm_ctx, msg)
            del users[user_id]
        del sessions[key]
    return


@clean_inactive_sessions.before_loop
async def wait_for_ready():
    print('Background tasks waiting...')
    await FishbowlBackend.bot.wait_until_ready()


@commands.command(name="changeprefix")
@check_no_dm()
@check_permission(server_owner=True)
async def change_prefix(ctx, prefix):
    prefix_changed = await FishbowlBackend.changeprefix(ctx.guild.id, prefix)
    if prefix_changed:
        return await FishbowlBackend.send_message(ctx, f'Prefix changed to: `{prefix}`')
    else:
        return await FishbowlBackend.send_error(ctx, 'Prefix change failed!')


@change_prefix.error
async def changeprefix_error(ctx, error):
    if isinstance(error, PermissionDenied):
        return await FishbowlBackend.send_error(ctx, "Insufficient permission for this command!")
    if isinstance(error, CommandCannotBeDMed):
        return await FishbowlBackend.send_error(ctx, "Can't use this command in DMs!")
    return await general_errors(ctx, error)


@commands.command()
async def start(ctx, *args):
    creator_id = ctx.author.id
    session_id = next((i for i in range(MAX_TOTAL_SESSIONS) if i not in sessions), None)
    if session_id is None:
        return await FishbowlBackend.send_error(ctx,
                                                "Bot is handling too many sessions right now! Please try again later!")

    if creator_id in users:
        return await FishbowlBackend.send_error(ctx, "Already in a session! (Session #`%s`)" % users[creator_id])
    users[creator_id] = session_id

    sessions[session_id] = {'bowl': [],
                            'discard': [],
                            'last_modified': "",
                            'players': {creator_id: []},
                            'creator': creator_id,
                            'home_channel': ctx.channel,
                            'total_scraps': 0,
                            'ban_list': []}
    session_update_time(session_id)
    return await FishbowlBackend.send_message(ctx,
                                              "Fishbowl session successfully created! (Session #%s)\n" % session_id +
                                              "Other users can join with `join %s`!" % session_id)

@start.error
async def start_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command()
async def join(ctx, *args):
    if len(args) == 0:
        return await FishbowlBackend.send_error(ctx, "Missing the ID of the session to join!")
    session_id = clean_session_id(args[0])
    user_id = ctx.author.id
    if user_id in users:
        return await FishbowlBackend.send_error(ctx, "Already in a session! (Session ID `%s`)" % users[user_id])
    if session_id not in sessions:
        return await FishbowlBackend.send_error(ctx, "Can't find Session #%s! Did you type it in correctly?" % session_id)

    if len(sessions[session_id]['players']) >= MAX_USERS_PER_SESSION:
        return await FishbowlBackend.send_error(ctx,
                                                "Session #%s is at its maximum of %d players! Please try again later!" %
                                                (session_id, MAX_USERS_PER_SESSION))
    if ctx.author.id in sessions[session_id]['ban_list']:
        return await FishbowlBackend.send_error(ctx,
                                                "Can't join! You were banned from Session #%s by the creator!" % session_id)

    sessions[session_id]['players'][user_id] = []
    users[user_id] = session_id
    session_update_time(session_id)

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_message(sessions[session_id]['home_channel'], "%s joined Session #%s!" % (ctx.author.mention, session_id))

    return await FishbowlBackend.send_message(ctx, "%s successfully joined Session #%s!" % (ctx.author.mention, session_id))


@join.error
async def join_error(ctx, error):
    return await general_errors(ctx, error)


@check_user_in_session()
@commands.command(name="session")
async def check_session(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_players = [await FishbowlBackend.find_user(k) for k in sessions[session_id]['players']]
    creator_user = await FishbowlBackend.find_user(sessions[session_id]['creator'])
    if creator_user is None:
        return await FishbowlBackend.send_error(ctx, "Oops, internal error!")
    session_update_time(session_id)
    valid_session_players = [user for user in session_players if user is not None]
    not_found_users = len(session_players) - len(valid_session_players)
    if not_found_users > 0:
        footer_msg = "Warning: Was not able to find %d users" % not_found_users
    else:
        footer_msg = ""
    session_info = {"Players": "\n".join(user_to_readable(user) for user in valid_session_players),
                    "Creator": user_to_readable(creator_user)}
    await FishbowlBackend.send_embed(ctx, "", title="Session #%s" % session_id, footer=footer_msg, fields=session_info)

    return


@check_user_in_session()
@commands.command(name="check")
async def check_bowl(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)
    session_players = sessions[session_id]['players']
    session_dict = {"Bowl Scraps": len(sessions[session_id]['bowl']),
                    "Discard Scraps": "%d" % len(sessions[session_id]['discard']),
                    "Player Hands": "\n".join(["%s: %d" % (await FishbowlBackend.find_user(player), len(session_players[player])) for player in session_players]),
                    "Total Scraps": "%d" % sessions[session_id]['total_scraps']}

    await FishbowlBackend.send_embed(ctx, "", title="Session #%s" % session_id, fields=session_dict)

    return


@check_bowl.error
@check_session.error
async def check_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command(aliases=["exit"])
@check_user_in_session()
async def leave(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    if session_id not in sessions:
        return await FishbowlBackend.send_error(ctx, "Oops! Internal error!")

    session_update_time(session_id)
    if len(args) > 0:
        try:
            new_creator = await commands.MemberConverter().convert(ctx, args[0])
        except commands.BadArgument:
            return await FishbowlBackend.send_error(ctx,
                                                      "Couldn't find the specified user! Try mentioning them!")
        if new_creator.id not in sessions[session_id]['players']:
            return await FishbowlBackend.send_error(ctx,
                                                      "Can't pass Creator status to someone not in the game!")
        if new_creator.id == user_id:
            return await FishbowlBackend.send_error(ctx,
                                                      "Can't pass the Creator status to yourself as you're leaving!")

    else:
        new_creator = ""

    creator_update = ""
    if sessions[session_id]['creator'] == user_id:
        if len(sessions[session_id]['players']) <= 1:
            await FishbowlBackend.send_message(ctx, "Last person leaving; closing session...")
            return await end(ctx, session_id)
        if not new_creator:
            new_creator_id = random.sample(sessions[session_id]['players'].keys(), 1)[0]
            new_creator = await FishbowlBackend.find_user(new_creator_id)
        if sessions[session_id]['home_channel'].type is discord.ChannelType.private:
            if sessions[session_id]['home_channel'].recipient.id == sessions[session_id]['creator']:
                sessions[session_id]['home_channel'] = await new_creator.create_dm()
        sessions[session_id]['creator'] = new_creator.id
        creator_update = "\nCreator of Session #%s is now %s!" % (session_id, new_creator.mention)

    sessions[session_id]['total_scraps'] -= len(sessions[session_id]['players'][user_id])
    del users[user_id]
    del sessions[session_id]['players'][user_id]

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_message(sessions[session_id]['home_channel'],
                                           "%s left Session #%s!" % (ctx.author.mention, session_id) + creator_update)

    return await FishbowlBackend.send_message(ctx,
                                              "%s successfully left Session #%s!" % (ctx.author.mention, session_id)
                                              + creator_update)


@leave.error
async def leave_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
@check_creator()
async def end(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]

    if session_id not in sessions:
        return await FishbowlBackend.send_error(ctx, "Oops, internal error!")

    notify_players = ctx.channel.type is discord.ChannelType.private and \
                     sessions[session_id]['home_channel'].type is discord.ChannelType.private

    for player_id in sessions[session_id]['players']:
        if notify_players and player_id != sessions[session_id]['creator']:
            player_user = await FishbowlBackend.find_user(player_id)
            player_dm = await player_user.create_dm()
            await FishbowlBackend.send_message(player_dm, "%s ended Session #%s!" % (ctx.author.mention, session_id))
        del users[player_id]

    del sessions[session_id]
    return await FishbowlBackend.send_message(ctx, "Session #%s ended!" % session_id)


@end.error
async def end_error(ctx, error):
    if isinstance(error, CreatorOnly):
        return await FishbowlBackend.send_error(ctx, "Only the creator of a session can end it!")
    return await general_errors(ctx, error)


async def add_master(ctx, scraps, to_hand=False):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    if (sessions[session_id]['total_scraps'] + len(scraps)) > MAX_BOWL_SIZE:
        await FishbowlBackend.send_embed(ctx,
                                         description="Too many scraps in the session! (Max: %d)" % MAX_BOWL_SIZE,
                                         footer="Scraps: %d (Session #%s)" % (sessions[session_id]['total_scraps'], session_id),
                                         color=FishbowlBackend.ERROR_EMBED_COLOR)
        return

    if any(len(scrap) > SCRAP_MAX_LEN for scrap in scraps):
        return await FishbowlBackend.send_error(ctx, "Scrap(s) too long! %d characters or less, please!" % SCRAP_MAX_LEN)

    bad_scraps = [s for s in scraps if check_scrap(s)]
    for s in bad_scraps:
        await FishbowlBackend.send_error(ctx, check_scrap(s))
        scraps.remove(s)

    sessions[session_id]['total_scraps'] += len(scraps)
    if to_hand:
        keywords = ("to their hand", "Hand")
        target_place = sessions[session_id]['players'][user_id]
    else:
        keywords = ("to the bowl", "Bowl")
        target_place = sessions[session_id]['bowl']
    target_place += scraps

    if not scraps:
        descript = "%s added... 0 scrap(s) %s! Huh?\n" % (ctx.author.mention, keywords[0])
        footer = ""
        if bad_scraps:
            return
    else:
        descript = "%s added %d scrap(s) %s!\n" % (ctx.author.mention, len(scraps), keywords[0])
        footer = "%s: %d (Session #%s)" % (keywords[1], len(target_place), session_id)
        if ctx.channel.id != sessions[session_id]['home_channel'].id:
            await FishbowlBackend.send_embed(sessions[session_id]['home_channel'], description=descript, footer=footer)

    await FishbowlBackend.send_embed(ctx, description=descript, footer=footer)
    return


@commands.command()
@check_user_in_session()
async def add(ctx, scraps: commands.Greedy[clean_scrap]):
    return await add_master(ctx, scraps, to_hand=False)


@commands.command(name="addtohand", aliases=["add2hand"])
@check_user_in_session()
async def add_to_hand(ctx, scraps: commands.Greedy[clean_scrap]):
    return await add_master(ctx, scraps, to_hand=True)


@add_to_hand.error
@add.error
async def add_error(ctx, error):
    return await general_errors(ctx, error)


async def draw_master(ctx, args, from_discard=False):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)
    try:
        args = int(args[0])
        is_int = True
    except ValueError:
        is_int = False

    if from_discard:
        source_pile = sessions[session_id]['discard']
        keyword = "discard pile"
    else:
        source_pile = sessions[session_id]['bowl']
        keyword = "bowl"

    had_err = False
    if is_int:
        if args < 0:
            return await FishbowlBackend.send_error(ctx, "Can't draw negative scraps!")
        if args == 0:
            drawn_scraps = []
            descript = "... 0 scraps from the %s! Huh?" % keyword
        elif args > len(source_pile):
            drawn_scraps = []
            descript = "Not enough scraps in the %s!" % keyword
            had_err = True
        else:
            drawn_scraps = random.sample(source_pile, args)
            [source_pile.remove(scrap) for scrap in drawn_scraps]
            descript = " %d scrap(s) from the %s" % (args, keyword)
    else:
        drawn_scraps = []
        fail_scraps = []
        for arg in args:
            match_scrap = next((s for s in source_pile if arg == s),
                               next((s for s in source_pile if arg.lower() == s.lower()), None))
            if match_scrap is None:
                fail_scraps.append(arg)
                continue
            drawn_scraps.append(match_scrap)
            source_pile.remove(match_scrap)

        if not drawn_scraps:
            descript = "Couldn't find any of those scraps in the %s!" % keyword
            had_err = True
        else:
            descript = " %d specific scrap(s) from the %s" % (len(args), keyword)

        if fail_scraps and not had_err:
            descript += "\nNote: Couldn't find `%s`" % "`, `".join(fail_scraps)

    sessions[session_id]['players'][user_id] += drawn_scraps

    if not had_err:
        public_msg = "%s drew%s!" % (ctx.author.mention, descript)
        private_msg = "You drew%s" % descript
        #if drawn_scraps:
        #    private_msg += ":\n`%s`" % "`, `".join(drawn_scraps)
    else:
        public_msg = descript
        private_msg = descript

    footer = "Hand: %d, Bowl: %d (Session #%s)" % (len(sessions[session_id]['players'][user_id]),
                                                   len(sessions[session_id]['bowl']),
                                                   session_id)

    if ctx.message.channel.type is not discord.ChannelType.private:
        await FishbowlBackend.send_embed(ctx, description=public_msg, footer=footer)

    if not had_err:
        if drawn_scraps:
            await list_send(ctx.author, description=private_msg, entries=drawn_scraps, footer=footer)
        else:
            await FishbowlBackend.send_embed(ctx.author, description=private_msg, footer=footer)

    if ctx.channel.id != sessions[session_id]['home_channel'].id and not had_err:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'], description=public_msg, footer=footer)

    return


async def list_send(ctx, description, entries, end_description="", title="", footer=""):
    list_char_lim = EMBED_DESCRIPTION_LIMIT
    delineator = "`, `"
    delin_len = len(delineator)
    split_list = []
    mini_list = []
    curr_len = 0

    for minientry in entries:
        curr_len += (len(minientry) + delin_len)
        if curr_len >= list_char_lim:
            split_list.append(mini_list)
            mini_list = []
            curr_len = len(minientry) + delin_len
        mini_list.append(minientry)

    if mini_list:
        split_list.append(mini_list)

    if len(split_list) == 1:
        if description:
            descript = description + ":\n"
        else:
            descript = description
        if end_description:
            end_descript = "\n" +end_description
        else:
            end_descript = ""

        return await FishbowlBackend.send_embed(ctx,
                                                title=title,
                                                description=descript + "`" + delineator.join(entries) + "`" + end_descript,
                                                footer=footer)

    if not description and title:
        descripts = ["" for i in range(len(split_list))]
        titles = [title+" (%d/%d)" % (i+1, len(split_list)) for i in range(len(split_list))]
    else:
        descripts = [description+" (%d/%d):\n" % (i+1, len(split_list)) for i in range(len(split_list))]
        titles = [title for i in range(len(split_list))]

    for i in range(len(split_list)):
        if i < len(split_list)-1:
            sub_foot = ""
            end_descript = ""
        else:
            sub_foot = footer
            if end_description:
                end_descript = "\n" + end_description
            else:
                end_descript = ""

        await FishbowlBackend.send_embed(ctx,
                                         title=titles[i],
                                         description=descripts[i]+"`"+delineator.join(split_list[i]) + "`" + end_descript,
                                         footer=sub_foot)
    return


@commands.command()
@check_user_in_session()
async def draw(ctx, scraps: commands.Greedy[clean_scrap]):
    if not scraps:
        args = ["1"]
    else:
        args = scraps
    return await draw_master(ctx, args, from_discard=False)


@commands.command(name="drawfromdiscard", aliases=["drawdiscard", "discarddraw"])
@check_user_in_session()
async def draw_from_discard(ctx, scraps: commands.Greedy[clean_scrap]):
    if not scraps:
        args = ["1"]
    else:
        args = scraps
    return await draw_master(ctx, args, from_discard=True)


@draw.error
@draw_from_discard.error
async def draw_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        return await FishbowlBackend.send_error(ctx, 'Give me an integer number of scraps to draw!')
    else:
        return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
async def peek(ctx, num_draw: int):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)
    if num_draw == 0:
        return await FishbowlBackend.send_embed(ctx,
                                                description="%s peeked at... 0 scraps! Huh?" % ctx.author.mention,
                                                footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))

    if num_draw > len(sessions[session_id]['bowl']):
        return await FishbowlBackend.send_embed(ctx,
                                                description="Not enough scraps in the bowl!\n",
                                                footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id),
                                                color=FishbowlBackend.ERROR_EMBED_COLOR)
    drawn_scraps = random.sample(sessions[session_id]['bowl'], num_draw)

    footer = "Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id)
    public_msg = "%s is peeking at %d scrap(s) in the bowl..." % (ctx.author.mention, num_draw)
    if ctx.message.channel.type is not discord.ChannelType.private:
        await FishbowlBackend.send_embed(ctx, description=public_msg, footer=footer)

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'], description=public_msg, footer=footer)

    return await list_send(ctx.author, description="You peek at %d scrap(s) in the bowl" % num_draw, entries=drawn_scraps, footer=footer)


@peek.error
async def peek_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, 'Need to give me a number of scraps to peek at!')
    elif isinstance(error, commands.BadArgument):
        return await FishbowlBackend.send_error(ctx, 'Give me an integer number of scraps to peek at!')
    else:
        return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
async def hand(ctx, show_keyword: typing.Optional[clean_scrap] = ''):
    public_show = False
    user_id = ctx.author.id
    if show_keyword:
        if show_keyword.lower() in ['show', 'public', 'force']:
            if ctx.message.channel.type is discord.ChannelType.private:
                return await FishbowlBackend.send_error(ctx, "Can't use `hand %s` in DMs!" % show_keyword)
            public_show = True
        else:
            return await FishbowlBackend.send_error(ctx, "Sorry, don't know what `%s` means!" % show_keyword)

    session_id = users[user_id]
    session_update_time(session_id)
    user_hand = sessions[session_id]['players'][user_id]
    if ctx.message.channel.type is not discord.ChannelType.private and not public_show:
        await FishbowlBackend.send_embed(ctx,
                                           "%s is checking their hand..." % ctx.author.mention,
                                           footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))
    if public_show:
        target_ctx = ctx
    else:
        target_ctx = ctx.author

    if user_hand:
        return await list_send(target_ctx,
                               title="%s's Hand" % ctx.author.name,
                               description="",
                               entries=user_hand,
                               footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))
    else:
        return await FishbowlBackend.send_embed(target_ctx,
                                         title="%s's Hand" % ctx.author.name,
                                         description="No scraps in hand!",
                                         footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))


@hand.error
async def hand_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
async def edit(ctx, old_word: clean_scrap, new_word: clean_scrap, *args):
    user_id = ctx.author.id
    if args:
        return await FishbowlBackend.send_error(ctx, "Too many arguments! To pass phrases with spaces, wrap the phrase in quotation marks!")

    session_id = users[user_id]
    session_update_time(session_id)
    user_hand = sessions[session_id]['players'][user_id]

    err_msg = check_scrap(new_word)
    if err_msg:
        return await FishbowlBackend.send_error(ctx, err_msg)
    if len(new_word) > SCRAP_MAX_LEN:
        return await FishbowlBackend.send_error(ctx, "New scrap exceeds max length! (%d char)" % SCRAP_MAX_LEN)

    try:
        word_i = user_hand.index(old_word)
        user_hand[word_i] = new_word

        if ctx.channel.id != sessions[session_id]['home_channel'].id:
            await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                             description="%s is changing a scrap in their hand!" % ctx.author.mention,
                                             footer="(Session #%s)" % (session_id))

        return await FishbowlBackend.send_embed(ctx,
                                                description="%s changed `%s` to `%s` in their hand!" % (
                                                ctx.author.mention, old_word, new_word),
                                                footer="(Session #%s)" % (session_id))
    except ValueError:
        pass
    try:
        word_i = sessions[session_id]['bowl'].index(old_word)
        if user_id != sessions[session_id]['creator']:
            return await FishbowlBackend.send_error(ctx, "Only the session creator can edit scraps in the bowl!")
        sessions[session_id]['bowl'][word_i] = new_word
        return await FishbowlBackend.send_embed(ctx,
                                                description="%s changed `%s` to `%s` in the bowl!" % (
                                                ctx.author.mention, old_word, new_word),
                                                footer="(Session #%s)" % (session_id))
    except ValueError:
        pass

    return await FishbowlBackend.send_error(ctx, "Couldn't find `%s`! (Must match exactly, including capitals!)" % old_word)


@edit.error
async def edit_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Need to give me both the word you're changing and the word you're changing it to!")
    else:
        return await general_errors(ctx, error)


def cut_off_list(char_limit, entries, delineator="`, `", end_part=" and more!"):
    delin_len = len(delineator)
    run_total = [0]
    curr_len = 0
    abbrv_char_limit = char_limit - len(end_part)
    end_early = False
    bad_limit = len(entries)
    for i in range(len(entries)):
        curr_len += (len(entries[i]) + delin_len)
        if curr_len >= char_limit:
            bad_limit = next((j for j in range(len(run_total)) if run_total[j] > abbrv_char_limit), len(run_total))
            end_early = True
            break
        run_total.append(curr_len)
    descript = "`%s`" % delineator.join(entries[0:bad_limit])
    if end_early:
        descript += end_part
    return descript


async def discard_destroy_return(ctx, scraps, func_type):
    keyword = func_type
    user_id = ctx.author.id

    session_id = users[user_id]
    session_update_time(session_id)
    success_discard = []
    fail_discard = []
    user_hand = sessions[session_id]['players'][user_id]
    if len(user_hand) == 0:
        return await FishbowlBackend.send_error(ctx, "%s doesn't have any scraps in their hand!" % ctx.author.mention)

    if 'hand' in func_type:
        success_discard = user_hand
        if func_type == 'discardhand':
            sessions[session_id]['discard'] += user_hand

        elif func_type == 'returnhand':
            sessions[session_id]['bowl'] += user_hand
        sessions[session_id]['players'][user_id] = []
        keyword = func_type[:-4]
    else:
        if len(scraps) == 0:
            return await FishbowlBackend.send_error(ctx, "Need to give me the scrap you're %sing!" % keyword)

        for scrap in scraps:
            # tries case-sensitive match first, then case-insensitive match
            match_scrap = next((s for s in user_hand if scrap == s),
                               next((s for s in user_hand if scrap.lower() == s.lower()), None))
            if match_scrap is None:
                fail_discard.append(scrap)
                continue
            user_hand.remove(match_scrap)
            if func_type in ['play', 'discard']:
                sessions[session_id]['discard'].append(match_scrap)
            elif func_type == 'return':
                sessions[session_id]['bowl'].append(match_scrap)
            success_discard.append(match_scrap)

    #TODO: discard/destroy/return random cards from your hand

    if 'destroy' in func_type:
        sessions[session_id]['total_scraps'] -= len(success_discard)

    big_footer = "Hand: %d, Bowl: %d, Discard: %d (Session #%s)" % (len(sessions[session_id]['players'][user_id]),
                                                                    len(sessions[session_id]['bowl']),
                                                                    len(sessions[session_id]['discard']),
                                                                    session_id)
    if fail_discard:
        the_fun = cut_off_list(char_limit=EMBED_FOOTER_LIMIT,  entries=fail_discard, end_part=", etc.")
        embed_footer = "\nNote: Couldn't find %s" % the_fun
    else:
        embed_footer = ""

    if not success_discard:
        return await FishbowlBackend.send_embed(ctx,
                                                description="%s %ss... 0 scraps from their hand! Huh?%s" % (ctx.author.mention, keyword, embed_footer),
                                                footer=big_footer)
    else:
        embed_descript = "%s %ss %d scrap(s) from their hand" % (ctx.author.mention, keyword, len(success_discard))
        await list_send(ctx, description=embed_descript, entries=success_discard, end_description=embed_footer,
                        footer=big_footer)
        embed_descript += "!"

        if ctx.channel.id != sessions[session_id]['home_channel'].id:
            await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                             description="%s %ss %d scrap(s) from their hand!" % (ctx.author.mention,
                                                                                  keyword,
                                                                                  len(success_discard)),
                                             footer=big_footer)


@commands.command(aliases=["play"])
@check_user_in_session()
async def discard(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type=ctx.invoked_with)


@commands.command()
@check_user_in_session()
async def destroy(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type=ctx.invoked_with)


@commands.command(name="return")
@check_user_in_session()
async def return_scrap(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type=ctx.invoked_with)


@commands.command(aliases=["playall", "discardhand", "discardall"])
@check_user_in_session()
async def playhand(ctx, *args):
    return await discard_destroy_return(ctx, [], func_type=ctx.command.name)


@commands.command(aliases=["destroyall"])
@check_user_in_session()
async def destroyhand(ctx, *args):
    return await discard_destroy_return(ctx, [], func_type=ctx.command.name)


@commands.command(aliases=["returnall"])
@check_user_in_session()
async def returnhand(ctx, *args):
    return await discard_destroy_return(ctx, [], func_type=ctx.command.name)


@discard.error
@destroy.error
@return_scrap.error
@playhand.error
@destroyhand.error
@returnhand.error
async def destroy_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command(aliases=["look"])
@check_user_in_session()
async def see(ctx, keyword: str, *args):
    user_id = ctx.author.id

    session_id = users[user_id]
    session_update_time(session_id)

    if args:
        return await FishbowlBackend.send_error(ctx, "Too many arguments!")

    if keyword.lower() in ['deck', 'bowl']:
        look_pile = sessions[session_id]['bowl']
        grammar_words = ["bowl", "Bowl"]
    elif keyword.lower() in ['discard', 'graveyard', 'grave']:
        look_pile = sessions[session_id]['discard']
        grammar_words = ["discard pile", "Discard"]
    else:
        return await FishbowlBackend.send_error(ctx,
                                                "Don't recognize `%s`! Use `bowl` to check the bowl, or `discard` to check the discard pile!" % keyword)

    footer = "%s: %d (Session #%s)" % (grammar_words[1], len(look_pile), session_id)

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                         description="%s checks the %s!" % (ctx.author.mention, keyword),
                                         footer=footer)
    if not look_pile:
        return await FishbowlBackend.send_embed(ctx, description="The %s is empty!" % grammar_words[0], footer=footer)
    else:
        return await list_send(ctx,
                               title="",
                               description="Current scraps in the %s" % grammar_words[0],
                               entries=look_pile,
                               footer=footer)


@see.error
async def see_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Give me `bowl` or `discard`!")
    else:
        return await general_errors(ctx, error)


@commands.command(name="show")
@check_user_in_session()
async def show_hand(ctx, dest: str):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    if dest.lower() in ['all', 'public', 'hand']:
        if ctx.message.channel.type is discord.ChannelType.private:
            return await FishbowlBackend.send_error(ctx, "Can't use `show %s` in DMs!" % dest)
        target_ctx = ctx
    else:
        try:
            target_user = await commands.MemberConverter().convert(ctx, dest)
        except commands.BadArgument:
            target_user = await username_session_lookup(session_id, dest)
            if target_user is None:
                return await FishbowlBackend.send_error(ctx,
                                                        "Can't find the player! Names are case sensitive; you can also mention them!")

        if target_user.id == user_id:
            return await FishbowlBackend.send_error(ctx, "Can't show your own hand to yourself! Try `hand` instead!")

        if target_user.id not in sessions[session_id]['players']:
            return await FishbowlBackend.send_error(ctx,
                                                    "%s isn't in the session!" % target_user.name)
        target_ctx = target_user

        if ctx.message.channel.type is discord.ChannelType.private:
            req_confirmed = await confirm_req(target_user,
                                              target_user,
                                              ctx.author,
                                              "%s is trying to show you their hand! Accept?" % ctx.author.mention,
                                              notify_users=True)
            if not req_confirmed:
                return

            await FishbowlBackend.send_embed(ctx,
                                             description="Showing %s your hand..." % target_user.name,
                                             footer="Session #%s" % session_id
                                             )
        else:
            req_confirmed = await confirm_req(ctx,
                                              target_user,
                                              ctx.author,
                                              "%s is trying to show %s their hand! Accept?" % (ctx.author.name, target_user.name),
                                              notify_users=False)
            if not req_confirmed:
                return
            await FishbowlBackend.send_embed(ctx,
                                             description="%s is showing %s their hand..." % (ctx.author.name, target_user.name),
                                             footer="Session #%s" % session_id
                                             )

    user_hand = sessions[session_id]['players'][user_id]
    if not user_hand:
        return await FishbowlBackend.send_embed(target_ctx,
                                   title="%s's Hand" % ctx.author.name,
                                   description="No scraps in hand!",
                                   footer="Hand: %d (Session #%s)" % (len(user_hand), session_id)
                                   )
    else:
        return await list_send(target_ctx,
                               title="%s's Hand" % ctx.author.name,
                               description="",
                               entries=user_hand,
                               footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))


@show_hand.error
async def show_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Tell me which user you're showing your hand to! (Case sensitive)\n" +
                                                "If you're showing the hand to all, do `show public` instead!")
    else:
        return await general_errors(ctx, error)


async def confirm_req(confirm_ctx, target_user, req_user, req_text, notify_users=True):
    if await FishbowlBackend.is_already_waiting(req_user, target_user):
        if confirm_ctx == target_user:
            callout_ctx = req_user
        else:
            callout_ctx = confirm_ctx
        await FishbowlBackend.send_error(callout_ctx, "Already waiting for a response from this user!")
        return False

    confirm_msg = await FishbowlBackend.send_message(confirm_ctx, req_text)
    await confirm_msg.add_reaction(EMOJI_Y)
    await confirm_msg.add_reaction(EMOJI_N)
    check_func = reaction_check(message=confirm_msg, author=target_user, emoji=(EMOJI_Y, EMOJI_N))
    try:
        reaction, user = await FishbowlBackend.wait_for_reaction(req_user, target_user,
                                                                 timeout=CONFIRM_TIME_OUT, check=check_func)
        if reaction.emoji == EMOJI_Y:
            if notify_users:
                await FishbowlBackend.send_message(confirm_ctx, "Request accepted!")
                await FishbowlBackend.send_message(req_user, "%s accepted your request!" % target_user)
        if reaction.emoji == EMOJI_N:
            if notify_users:
                await FishbowlBackend.send_message(confirm_ctx, "Request denied!")
                await FishbowlBackend.send_message(req_user, "%s denied your request!" % target_user)
        await confirm_msg.remove_reaction(EMOJI_Y, FishbowlBackend.bot.user)
        await confirm_msg.remove_reaction(EMOJI_N, FishbowlBackend.bot.user)
        return reaction.emoji == EMOJI_Y

    except asyncio.TimeoutError:
        await FishbowlBackend.send_message(confirm_ctx, "Request timed out!")
        if notify_users:
            await FishbowlBackend.send_message(req_user, "Request timed out!")
        await confirm_msg.remove_reaction(EMOJI_Y, FishbowlBackend.bot.user)
        await confirm_msg.remove_reaction(EMOJI_N, FishbowlBackend.bot.user)
        pass
    return False


async def pass_take(ctx, dest, scraps, pass_flag=True):
    user_id = ctx.author.id
    if not scraps:
        return await FishbowlBackend.send_error(ctx, "Need to give me the scrap you want to take or pass!")
    session_id = users[user_id]
    session_update_time(session_id)

    try:
        target_user = await commands.MemberConverter().convert(ctx, dest)
    except commands.BadArgument:
        target_user = await username_session_lookup(session_id, dest)
        if target_user is None:
            return await FishbowlBackend.send_error(ctx,
                                                    "Can't find the player! Names are case sensitive; you can also mention them!")

    if target_user.id not in sessions[session_id]['players']:
        return await FishbowlBackend.send_error(ctx, "%s isn't in the session!" % target_user.name)

    if pass_flag:
        source_user = ctx.author
        dest_user = target_user
        keyword1 = ("passed", "to")
        keyword2 = ("pass", "to")
    else:
        source_user = target_user
        dest_user = ctx.author
        keyword1 = ("had", "taken from them by")
        keyword2 = ("take", "from")

    if target_user.id == ctx.author.id:
        return await FishbowlBackend.send_error(ctx, "Can't %s %s yourself!" % (keyword2[0], keyword2[1]))

    source_hand = sessions[session_id]['players'][source_user.id].copy()
    dest_hand = sessions[session_id]['players'][dest_user.id].copy()
    success_scraps = []
    fail_scraps = []
    word_scrap = True

    for scrap in scraps:
        match_scrap = next((s for s in source_hand if scrap == s),
                           next((s for s in source_hand if scrap.lower() == s.lower()), None))

        if match_scrap is None:
            fail_scraps.append(scrap)
            continue

        success_scraps.append(match_scrap)
        source_hand.remove(match_scrap)
        dest_hand.append(match_scrap)

    if not success_scraps:
        try:
            num_pass = int(scraps[0])
            if num_pass > len(source_hand):
                return await FishbowlBackend.send_embed(ctx,
                                                        description="%s doesn't have enough scraps in hand!" % source_user.name,
                                                        footer="%s's Hand: %d (Session #%s)" % (source_user.name,
                                                                                                len(source_hand),
                                                                                                session_id))
            success_scraps = random.sample(source_hand, num_pass)
            [source_hand.remove(scrap) for scrap in success_scraps]
            dest_hand += success_scraps
            fail_scraps = []
            word_scrap = False
        except ValueError:
            pass

    footer_msg = "%s's Hand: %d, %s's Hand: %d (Session #%s)" % (source_user.name, len(source_hand),
                                                                 dest_user.name, len(dest_hand), session_id)

    if fail_scraps:
        not_found_list = cut_off_list(char_limit=EMBED_FOOTER_LIMIT,  entries=fail_scraps, end_part=", etc.")
        embed_footer = "\nNote: Couldn't find %s" % not_found_list
    else:
        embed_footer = ""

    if success_scraps:
        if ctx.message.channel.type is discord.ChannelType.private:
            confirm_ctx = target_user
            confirm_msg = "%s is trying to %s %d scrap(s) %s you" % (ctx.author.mention, keyword2[0], len(success_scraps),
                                                                     keyword2[1])
            descript = ""
        else:
            confirm_ctx = ctx
            confirm_msg = "%s is trying to %s %d scrap(s) %s %s" % (ctx.author.mention, keyword2[0], len(success_scraps),
                                                                    keyword2[1], target_user.mention)

            if word_scrap:
                # public message???
                descript = "%s %s %d scrap(s) %s %s:" % (source_user.mention,  # User1
                                                           keyword1[0],  # passed/took
                                                           len(success_scraps),
                                                           keyword1[1],  # to/from
                                                           dest_user.mention)  # User2)
            else:
                descript = "%s %s %d scrap(s) %s %s!" % (source_user.mention,  # User1
                                                           keyword1[0],  # passed/took
                                                           len(success_scraps),
                                                           keyword1[1],  # to/from
                                                           dest_user.mention)  # User2)
        if word_scrap:
            cut_list = cut_off_list(EMBED_DESCRIPTION_LIMIT, entries=success_scraps, end_part=", etc.")
            confirm_msg += ":\n`%s`\n" % cut_list
            descript += ":\n`%s`\n" % cut_list
        else:
            confirm_msg += "! "

        req_confirmed = await confirm_req(confirm_ctx,
                                          target_user,
                                          ctx.author,
                                          confirm_msg + "Accept?",
                                          notify_users=(ctx.message.channel.type is discord.ChannelType.private))
        if not req_confirmed:
            return

        # DM people if DMs OR if people are passing random scraps in public
        if ctx.message.channel.type is discord.ChannelType.private or not word_scrap:
            if pass_flag:
                await list_send(dest_user,
                                description="%s passed you %d scrap(s)" % (source_user.mention, len(success_scraps)),
                                entries=success_scraps,
                                footer=footer_msg)
                await list_send(source_user,
                                description="You passed %s %d scrap(s)" % (dest_user.mention, len(success_scraps)),
                                entries=success_scraps,
                                footer=footer_msg,
                                end_description=embed_footer)
            else:
                await list_send(dest_user,
                                description="You took %d scrap(s) from %s" % (len(success_scraps), source_user.mention),
                                entries=success_scraps,
                                footer=footer_msg,
                                end_description=embed_footer)

                await list_send(source_user,
                                description="%s took %d scrap(s) from you" % (dest_user.mention, len(success_scraps)),
                                entries=success_scraps,
                                footer=footer_msg)

    else:
        descript = "%s %s... 0 scraps %s %s! Huh?" % (source_user.mention,
                                                      keyword1[0],
                                                      keyword1[1],
                                                      dest_user.mention)

    sessions[session_id]['players'][source_user.id] = source_hand
    sessions[session_id]['players'][dest_user.id] = dest_hand

    # Pastes a notification message in the home channel if needed
    if ctx.channel.id != sessions[session_id]['home_channel'].id and (sessions[session_id]['home_channel'].id != dest_user.dm_channel.id):
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                         description="%s %s %d scrap(s) %s %s!" % (source_user.mention,  # User1
                                                                          keyword1[0],  # passed/took
                                                                          len(success_scraps),
                                                                          keyword1[1],  # to/from
                                                                          dest_user.mention),  # User2,
                                         footer=footer_msg)

    # notify sender of status
    if descript and (ctx.channel.id != source_user.dm_channel.id) or not success_scraps:
        await FishbowlBackend.send_embed(ctx, description=descript+embed_footer, footer=footer_msg)

    return


@commands.command(name='pass', aliases=['give'])
@check_user_in_session()
async def pass_scrap(ctx, dest: str, scraps: commands.Greedy[clean_scrap]):
    return await pass_take(ctx, dest, scraps, pass_flag=True)


@pass_scrap.error
async def pass_err(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Missing an argument!\n"+
                                                "Give me both the player you're passing to and the scraps you're passing!")
    else:
        return await general_errors(ctx, error)


@commands.command(name='take', aliases=['steal'])
@check_user_in_session()
async def take_scrap(ctx, dest: str, scraps: commands.Greedy[clean_scrap]):
    return await pass_take(ctx, dest, scraps, pass_flag=False)


@take_scrap.error
async def take_err(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Missing an argument!\n"+
                                                "Give me both the player you're taking from and the scraps you're taking!")
    else:
        return await general_errors(ctx, error)


@commands.command(name="recall")
@check_user_in_session()
@check_creator()
async def recall_hands(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    session_players = sessions[session_id]['players']
    [sessions[session_id]['bowl'].extend(session_players[k]) for k in session_players]
    sessions[session_id]['players'] = {k: [] for k in session_players}

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                         description="%s recalled all hands back to the bowl!" % ctx.author.mention,
                                         footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))

    return await FishbowlBackend.send_embed(ctx,
                                            description="Recalling all hands back to the bowl!",
                                            footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))


@commands.command()
@check_user_in_session()
@check_creator()
async def shuffle(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    sessions[session_id]['bowl'].extend(sessions[session_id]['discard'])
    sessions[session_id]['discard'] = []

    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                         description="%s shuffled the discard pile back into the bowl!" % ctx.author.mention,
                                         footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))

    return await FishbowlBackend.send_embed(ctx,
                                            description="Shuffling the discard pile back into the bowl!",
                                            footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))


@shuffle.error
@recall_hands.error
async def recall_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command(name="reset", aliases=['empty', 'dump'])
@check_user_in_session()
@check_creator()
async def empty_reset(ctx, arg: clean_arg):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    discard_all = arg in ['all', 'session']
    descripts = []
    if discard_all or arg in ['bowl', 'deck']:
        descripts.append("bowl")
        sessions[session_id]['bowl'] = []
    if discard_all or arg in ['discard', 'graveyard', 'trash']:
        descripts.append("discard pile")
        sessions[session_id]['discard'] = []
    if discard_all or arg in ['hands']:
        descripts.append("player hands")
        sessions[session_id]['players'] = {k: [] for k in sessions[session_id]['players']}
    sessions[session_id]['total_scraps'] = len(sessions[session_id]['bowl']) + \
                                           len(sessions[session_id]['discard']) + \
                                           sum(len(sessions[session_id]['players'][p_id]) for p_id in sessions[session_id]['players'])

    if len(descripts) <= 2:
        descriptions = "and ".join(descripts)
    else:
        descriptions = ", ".join(descripts[:-1])
        descriptions += (", and " + descripts[-1])
    if ctx.channel.id != sessions[session_id]['home_channel'].id:
        await FishbowlBackend.send_embed(sessions[session_id]['home_channel'],
                                         description="%s emptied the %s!" % (ctx.author.mention, descriptions),
                                         footer="(Session #%s)" % session_id)

    return await FishbowlBackend.send_embed(ctx,
                                            description="Emptying the %s!" % descriptions,
                                            footer="(Session #%s)" % session_id)


@empty_reset.error
async def empty_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Give me `all`, `bowl`, `discard`, or `hands` to empty it!")
    else:
        return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
@check_creator()
async def ban(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    if not args:
        return await FishbowlBackend.send_error(ctx,
                                                "Please tell me which user(s) you want to unban!")

    for arg in args:
        try:
            target_user = await commands.MemberConverter().convert(ctx, arg)
        except commands.BadArgument:
            target_user = await username_session_lookup(session_id, arg)
            if target_user is None:
                return await FishbowlBackend.send_error(ctx,
                                                        "Can't find %s! Names are case sensitive; you can also mention them!" % arg)

        if target_user.id in sessions[session_id]['ban_list']:
            await FishbowlBackend.send_error(ctx, "%s is already banned from Session #%s!" % (target_user.mention, session_id))
            continue
        if target_user.id == ctx.author.id:
            await FishbowlBackend.send_error(ctx, "Can't ban yourself!")
            continue
        if target_user.id == FishbowlBackend.bot.user.id:
            await FishbowlBackend.send_error(ctx, "Sorry, can't ban me!")
            continue
        sessions[session_id]['ban_list'].append(target_user.id)
        if target_user.id in sessions[session_id]['players']:
            sessions[session_id]['total_scraps'] -= len(sessions[session_id]['players'][target_user.id])
            del sessions[session_id]['players'][target_user.id]
            del users[target_user.id]
        await FishbowlBackend.send_message(ctx, "%s banned %s from Session #%s!" % (ctx.author.mention,
                                                                                    target_user.mention,
                                                                                    session_id))
    return


@commands.command()
@check_user_in_session()
@check_creator()
async def unban(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    if not args:
        return await FishbowlBackend.send_error(ctx,
                                                "Please tell me which user(s) you want to unban!")

    for arg in args:
        try:
            target_user = await commands.MemberConverter().convert(ctx, arg)
        except commands.BadArgument:
            target_user = await username_session_lookup(session_id, arg)
            if target_user is None:
                return await FishbowlBackend.send_error(ctx,
                                                        "Can't find %s! Names are case sensitive; you can also mention them!" % arg)
        if target_user.id == ctx.author.id:
            await FishbowlBackend.send_error(ctx, "Can't unban yourself!")
            continue
        if target_user.id == FishbowlBackend.bot.user.id:
            await FishbowlBackend.send_error(ctx, "Sorry, can't unban me!")
            continue
        if target_user.id not in sessions[session_id]['ban_list']:
            await FishbowlBackend.send_error(ctx, "Can't find %s in the banlist!" % target_user.mention)
            continue
        sessions[session_id]['ban_list'].remove(target_user.id)
        await FishbowlBackend.send_message(ctx, "%s has unbanned %s from Session #%s!" % (ctx.author.mention,
                                                                                     target_user.mention,
                                                                                     session_id))
    return


@ban.error
@unban.error
async def ban_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, 'Please tell me which users you want to ban!')
    else:
        return await general_errors(ctx, error)


@commands.command(name="commands", aliases=["command"])
async def list_commands(ctx, *args):
    grouped_df = help_df.sort_values(['Command'], ascending=True).groupby("Category")
    for groupname, groupdf in grouped_df:
        bot_command_dict = {cmd: cmd_help for cmd, cmd_help in zip(groupdf["CommandExample"], groupdf["Help"])}
        await FishbowlBackend.send_embed(ctx, "",
                                         fields=bot_command_dict,
                                         title="%s Commands:" % groupname)
    return


@commands.command(name="help")
async def help_bot(ctx, keyword: clean_arg = ""):
    if not keyword:
        return await FishbowlBackend.send_message(ctx, "I'm **FishbowlBot**, a Discord bot for games where you put a bunch of scraps in a bowl, hat, or what have you, then take them out!\n\n" +
                                                  "Start a Fishbowl session with `start`, then have other players join in! Everyone can add scraps with `add` and draw from the bowl using `draw`. You can also `edit` scraps, `pass` them to other players, and more!\n\n" +
                                                  "You can also DM me commands, using the default prefix `%s`! Good if you want to add words to the bowl without revealing them.\n\n" % FishbowlBackend.DEFAULT_PREFIX +
                                                  "For a list of all commands, do `help commands`. You can also ask me for detailed help with a specific command. (i.e. `help start`)")
    if keyword in ["all", "commands", "command", "list"]:
        return await list_commands(ctx, [])
    if keyword in help_df.index:
        if help_df.loc[keyword]["Aliases"]:
            footer = "Can also be invoked with: " + help_df.loc[keyword]["Aliases"]
        else:
            footer = ""
        return await FishbowlBackend.send_embed(ctx,
                                                "**%s**:\n" % help_df.loc[keyword]["CommandExample"] + help_df.loc[keyword]["DetailedHelp"],
                                                footer=footer)
    else:
        return await FishbowlBackend.send_error(ctx, "Don't recognize that help query! Try `help commands` for a list of all commands, or ask me for a specific command! (i.e. `help start`)")


@list_commands.error
@help_bot.error
async def help_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command(name="bugreport")
async def bug_report(ctx, *, arg: str):
    bugreport_ch = FishbowlBackend.bot.get_channel(BUG_REPORT_CHANNEL)
    await FishbowlBackend.send_embed(bugreport_ch,
                                     description=arg,
                                     footer="Submitted by %s" % str(ctx.author),
                                     color=FishbowlBackend.BUG_EMBED_COLOR)
    return await FishbowlBackend.send_embed(ctx, "Bug report sent! Thank you!")


@bug_report.error
async def bugreport_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, 'Please provide a description of the bug!')
    else:
        return await general_errors(ctx, error)


def setup():
    bot_commands = [globals()[cmd] for cmd in help_df["Function"]]
    for bot_command in bot_commands:
        FishbowlBackend.bot.add_command(bot_command)
    #FishbowlBackend.bot.add_command(help_bot)
    clean_inactive_sessions.start()


def get_user_alt_prefix(user_id):
    if user_id in users:
        return sessions[users[user_id]]["home_channel"]
    return None


setup()
FishbowlBackend.bot.run(token)
