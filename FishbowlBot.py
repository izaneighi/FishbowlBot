# bot.py
import os
import json
import discord
from discord.ext import commands
from dotenv import load_dotenv
import FishbowlBackend
import datetime
import random
import typing
import traceback
import asyncio
import pandas as pd

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

MAX_USER_SESSIONS = 1
MAX_TOTAL_SESSIONS = 100
MAX_BOWL_SIZE = 999
CONFIRM_TIME_OUT = 10.0

EMOJI_Y = "\N{THUMBS UP SIGN}"
EMOJI_N = "\N{THUMBS DOWN SIGN}"

help_df = pd.read_csv(r"Fishbowl_help.tsv", index_col="Command", sep="\t").fillna('')
help_df["DetailedHelp"] = help_df["DetailedHelp"].str.replace('\\\\n', '\n', regex=True)
bot_command_dict = {cmd: cmd_help for cmd, cmd_help in zip(help_df["CommandExample"], help_df["Help"])}

sessions = {}
users = {}


class CreatorOnly(commands.CheckFailure):
    pass


class UserNotInSession(commands.CheckFailure):
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


async def general_errors(ctx, error):
    if isinstance(error, UserNotInSession):
        return await FishbowlBackend.send_error(ctx, "You are currently not in a session!")
    if isinstance(error, commands.ExpectedClosingQuoteError) or isinstance(error, commands.InvalidEndOfQuotedStringError):
        return await FishbowlBackend.send_error(ctx, str(error))
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


@commands.command()
async def test(ctx, *args):
    await FishbowlBackend.send_message(ctx, '{} arguments: {}'.format(len(args), ', '.join(args)))
    return


@commands.command()
async def start(ctx, *args):
    num_sessions = len(sessions)
    if len(sessions) > MAX_TOTAL_SESSIONS:
        return await FishbowlBackend.send_message(ctx, "Bot is handling too many sessions right now! Please try again later!" % MAX_TOTAL_SESSIONS)

    creator_id = ctx.author.id
    session_id = str(num_sessions)

    if creator_id in users:
        return await FishbowlBackend.send_message(ctx,
                                                  "Already in a session! (Session #`%s`)" % users[creator_id])
    users[creator_id] = session_id

    sessions[session_id] = {'bowl': [],
                            'discard': [],
                            'last_modified': "",
                            'players': {creator_id: []},
                            'creator': creator_id,
                            'total_scraps': 0}
    session_update_time(session_id)
    return await FishbowlBackend.send_message(ctx,
                                              "Fishbowl session successfully created! (Session #%s)\n" % session_id +
                                              "Other users can join with `join %s`!" % session_id)


@commands.command()
async def join(ctx, *args):
    if len(args) == 0:
        return await FishbowlBackend.send_error(ctx, "Missing the ID of the session to join!")
    session_id = clean_session_id(args[0])

    user_id = ctx.author.id
    if user_id in users:
        return await FishbowlBackend.send_message(ctx,
                                                  "Already in a session! (Session ID `%s`)" % users[user_id])
    if session_id not in sessions:
        return await FishbowlBackend.send_message(ctx, "Can't find Session #%s! Did you type it in correctly?" % session_id)

    sessions[session_id]['players'][user_id] = []
    users[user_id] = session_id
    session_update_time(session_id)
    return await FishbowlBackend.send_message(ctx, "%s successfully joined Session #%s!" % (ctx.author.mention, session_id))


@check_user_in_session()
@commands.command(name="session")
async def check_session(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_players = [await FishbowlBackend.find_user(k) for k in sessions[session_id]['players']]
    creator_user = await FishbowlBackend.find_user(sessions[session_id]['creator'])
    if creator_user is None:
        return await FishbowlBackend.send_error(ctx, "Oops, internal error!")

    valid_session_players = [user for user in session_players if not None]
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
        return await FishbowlBackend.send_message(ctx,
                                                  "Oops! Internal error!" % session_id)

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
        sessions[session_id]['creator'] = new_creator.id
        creator_update = "\nCreator of Session #%s is now %s!" % (session_id, new_creator.mention)

    del users[user_id]
    del sessions[session_id]['players'][user_id]
    session_update_time(session_id)
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
        return await FishbowlBackend.send_message(ctx, "Oops, internal error!")

    for player_id in sessions[session_id]['players']:
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
    else:
        descript = "%s added %d scrap(s) %s!\n" % (ctx.author.mention, len(scraps), keywords[0])

    await FishbowlBackend.send_embed(ctx,
                                     description=descript,
                                     footer="%s: %d (Session #%s)" % (keywords[1], len(target_place), session_id))
    return


@commands.command()
@check_user_in_session()
async def add(ctx, scraps: commands.Greedy[clean_scrap]):
    return await add_master(ctx, scraps, to_hand=False)


@commands.command(name="addtohand")
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
            return await FishbowlBackend.send_error("Can't draw negative scraps!")
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
            if arg in source_pile:
                drawn_scraps.append(arg)
                source_pile.remove(arg)
            else:
                fail_scraps.append(arg)

        if not drawn_scraps:
            descript = "Couldn't find any of those scraps in the %s!" % keyword
            had_err = True
        else:
            descript = " %d scrap(s) from the %s" % (len(args), keyword)

        if fail_scraps and not had_err:
            descript += "\nNote: Couldn't find `%s`" % "`, `".join(fail_scraps)

    sessions[session_id]['players'][user_id] += drawn_scraps

    if not had_err:
        public_msg = "%s drew%s!" % (ctx.author.mention, descript)
        private_msg = "You drew%s" % descript
        if drawn_scraps:
            private_msg += ":\n`%s`" % "`, `".join(drawn_scraps)
    else:
        public_msg = descript
        private_msg = descript

    footer = "Hand: %d, Bowl: %d (Session #%s)" % (len(sessions[session_id]['players'][user_id]),
                                                   len(sessions[session_id]['bowl']),
                                                   session_id)

    if ctx.message.channel.type is not discord.ChannelType.private:
        await FishbowlBackend.send_embed(ctx, description=public_msg, footer=footer)
        if not had_err:
            await FishbowlBackend.send_embed(ctx.author, description=private_msg, footer=footer)
    else:
        await FishbowlBackend.send_embed(ctx.author, description=private_msg, footer=footer)

    return


@commands.command()
@check_user_in_session()
async def draw(ctx, args: commands.Greedy[clean_scrap]=["1"]):
    return await draw_master(ctx, args, from_discard=False)
    return


@commands.command(name="drawfromdiscard", aliases=["drawdiscard", "discarddraw"])
@check_user_in_session()
async def draw_from_discard(ctx, args: commands.Greedy[clean_scrap]=["1"]):
    return await draw_master(ctx, args, from_discard=True)
    return


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
    if num_draw == 0:
        return await FishbowlBackend.send_embed(ctx,
                                                description="%s peeked at... 0 scraps! Huh?" % ctx.author.mention,
                                                footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id),
                                                color=FishbowlBackend.DEFAULT_EMBED_COLOR)

    if num_draw > len(sessions[session_id]['bowl']):
        return await FishbowlBackend.send_embed(ctx,
                                                description="Not enough scraps in the bowl!\n",
                                                footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id),
                                                color=FishbowlBackend.ERROR_EMBED_COLOR)
    drawn_scraps = random.sample(sessions[session_id]['bowl'], num_draw)

    await FishbowlBackend.send_embed(ctx,
                                     description="%s is peeking at %d scrap(s) in the bowl..." % (ctx.author.mention, num_draw),
                                     footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id),
                                     color=FishbowlBackend.DEFAULT_EMBED_COLOR)


    await FishbowlBackend.send_embed(ctx.author,
                                     description="You peek at %d scrap(s) in the bowl:\n`%s`" % (num_draw, "`, `".join(drawn_scraps)),
                                     footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id),
                                     color=FishbowlBackend.DEFAULT_EMBED_COLOR)
    session_update_time(session_id)
    return


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
    user_hand = sessions[session_id]['players'][user_id]
    if ctx.message.channel.type is not discord.ChannelType.private and not public_show:
        await FishbowlBackend.send_embed(ctx,
                                           "%s is checking their hand..." % ctx.author.mention,
                                           footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))
    if user_hand:
        hand_list = "`%s`" % "`, `".join(user_hand)
    else:
        hand_list = "No scraps in hand!"
    if public_show:
        target_ctx = ctx
    else:
        target_ctx = ctx.author
    await FishbowlBackend.send_embed(target_ctx,
                                     title="%s's Hand:" % ctx.author.name,
                                     description=hand_list,
                                     footer="Hand: %d (Session #%s)" % (len(user_hand), session_id))

    session_update_time(session_id)
    return


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

    try:
        word_i = user_hand.index(old_word)
        user_hand[word_i] = new_word
        return await FishbowlBackend.send_embed(ctx,
                                                description="%s changed `%s` to `%s` in their hand!" % (
                                                ctx.author.mention, old_word, new_word),
                                                footer="Session #%s" % (session_id))
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
                                                footer="Session #%s" % (session_id))
    except ValueError:
        pass

    return await FishbowlBackend.send_error(ctx, "Couldn't find `%s`! (Must match exactly, including capitals!)" % old_word)


@edit.error
async def edit_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Need to give me both the word you're changing and the word you're changing it to!")
    else:
        return await general_errors(ctx, error)


async def discard_destroy_return(ctx, scraps, func_type):
    keyword = func_type
    user_id = ctx.author.id
    if len(scraps) == 0:
        return await FishbowlBackend.send_error(ctx, "Need to give me the scrap you're %sing!" % keyword)

    session_id = users[user_id]
    session_update_time(session_id)
    success_discard = []
    fail_discard = []
    user_hand = sessions[session_id]['players'][user_id]
    if len(user_hand) == 0:
        return await FishbowlBackend.send_error(ctx, "%s doesn't have any scraps in their hand!" % ctx.author.mention)

    # you SURE this is a command to toss your hand?
    if scraps[0] == 'hand' and len(scraps) == 1 and 'hand' not in scraps:
        success_discard = user_hand
        if func_type == 'discard':
            sessions[session_id]['discard'] += user_hand
        elif func_type == 'return':
            sessions[session_id]['bowl'] += user_hand
        sessions[session_id]['players'][user_id] = []
    else:
        for scrap in scraps:
            if scrap in user_hand:
                user_hand.remove(scrap)
                if func_type == 'discard':
                    sessions[session_id]['discard'].append(scrap)
                elif func_type == 'return':
                    sessions[session_id]['bowl'].append(scrap)
                success_discard.append(scrap)
            else:
                fail_discard.append(scrap)
                continue

    #TODO: discard/destroy/return random cards from your hand

    if func_type == 'destroy':
        sessions[session_id]['total_scraps'] -= len(success_discard)

    if not success_discard:
        embed_descript = "%s %ss... 0 scraps from their hand! Huh?" % (ctx.author.mention, keyword)
    else:
        embed_descript = "%s %ss from their hand...\n`%s`" % (ctx.author.mention,
                                                             keyword,
                                                             "`, `".join(success_discard))
    if fail_discard:
        embed_descript += "\nNote: Couldn't find %s!" % ", ".join(fail_discard)

    return await FishbowlBackend.send_embed(ctx,
                                            description=embed_descript,
                                            footer="Hand: %d, Bowl: %d, Discard: %d (Session #%s)" % (len(sessions[session_id]['players'][user_id]),
                                                                                                      len(sessions[session_id]['bowl']),
                                                                                                      len(sessions[session_id]['discard']),
                                                                                                      session_id))


@commands.command(aliases=["play"])
@check_user_in_session()
async def discard(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type='discard')


@commands.command()
@check_user_in_session()
async def destroy(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type='destroy')


@commands.command(name="return")
@check_user_in_session()
async def return_scrap(ctx, scraps: commands.Greedy[clean_scrap]):
    return await discard_destroy_return(ctx, scraps, func_type='return')


@discard.error
@destroy.error
@return_scrap.error
async def destroy_error(ctx, error):
    return await general_errors(ctx, error)


@commands.command()
@check_user_in_session()
async def see(ctx, keyword: str, *args):
    user_id = ctx.author.id

    session_id = users[user_id]
    session_update_time(session_id)

    if args:
        return await FishbowlBackend.send_error(ctx, "Too many arguments!")

    if keyword.lower() in ['deck', 'bowl']:
        bowl_list = sessions[session_id]['bowl']
        if len(bowl_list) == 0:
            descript = "Bowl is empty!"
        else:
            descript = "Current scraps in the bowl:\n`%s`" % "`, `".join(bowl_list)
        return await FishbowlBackend.send_embed(ctx,
                                                description=descript,
                                                footer="Bowl: %d (Session #%s)" % (len(bowl_list), session_id)
                                                )
    if keyword.lower() in ['discard', 'graveyard', 'grave']:
        discard_list = sessions[session_id]['discard']
        if len(discard_list) == 0:
            descript = "Discard pile is empty!"
        else:
            descript = "Current scraps in the discard pile:\n`%s`" % "`, `".join(discard_list)
        return await FishbowlBackend.send_embed(ctx,
                                                description=descript,
                                                footer="Discard: %d (Session #%s)" % (len(discard_list), session_id)
                                                )
    else:
        return await FishbowlBackend.send_error(ctx,
                                                "Don't recognize `%s`! Use `bowl` to check the bowl, or `discard` to check the discard pile!" % keyword)


@see.error
async def see_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Give me `bowl`, `discard`, or mention the player!")
    else:
        return await general_errors(ctx, error)


@commands.command(name="show")
@check_user_in_session()
async def show_hand(ctx, dest: str):
    user_id = ctx.author.id
    session_id = users[user_id]
    session_update_time(session_id)

    if dest.lower() in ['all', 'public']:
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
                                                        "Can't find the player! Trying mentioning them or their full username!")

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
        descript = "No scraps in their hand!"
    else:
        descript = "`%s`" % "`, `".join(user_hand)
    return await FishbowlBackend.send_embed(target_ctx,
                                            title="%s's Hand:" % ctx.author.name,
                                            description=descript,
                                            footer="Hand: %d (Session #%s)" % (len(user_hand), session_id)
                                            )


@show_hand.error
async def show_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Tell me which user you're showing your hand to!\n" +
                                                "If you're showing the hand to all, do `show all` instead!")
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
        return await FishbowlBackend.send_error(ctx, "Need to give me the scrap you want to pass!")
    session_id = users[user_id]
    session_update_time(session_id)

    try:
        target_user = await commands.MemberConverter().convert(ctx, dest)
    except commands.BadArgument:
        target_user = await username_session_lookup(session_id, dest)
        if target_user is None:
            return await FishbowlBackend.send_error(ctx,
                                                    "Can't find %s! Trying mentioning them or their full username!" % dest)

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
        return await FishbowlBackend.send_error(ctx, "Can't %s to yourself!" % keyword2[0])

    source_hand = sessions[session_id]['players'][source_user.id].copy()
    dest_hand = sessions[session_id]['players'][dest_user.id].copy()
    success_scraps = []
    fail_scraps = []

    for scrap in scraps:
        if scrap in source_hand:
            success_scraps.append(scrap)
            source_hand.remove(scrap)
            dest_hand.append(scrap)
        else:
            fail_scraps.append(scrap)

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
        except ValueError:
            pass

    footer_msg = "%s's Hand: %d, %s's Hand: %d (Session #%s)" % (source_user.name, len(source_hand),
                                                                 dest_user.name, len(dest_hand), session_id)

    if success_scraps:
        descript = "%s %s %d scrap(s) %s %s:\n`%s`" % (source_user.mention, # User1
                                                       keyword1[0], # passed/took
                                                       len(success_scraps),
                                                       keyword1[1], # to/from
                                                       dest_user.mention,  # User2
                                                       "`, `".join(success_scraps))

        if ctx.message.channel.type is discord.ChannelType.private:
            req_confirmed = await confirm_req(target_user,
                                              target_user,
                                              ctx.author,
                                              "%s is trying to %s %d scraps %s you! Accept?" % (ctx.author.mention,
                                                                                                keyword2[0],
                                                                                                len(scraps),
                                                                                                keyword2[1]),
                                              notify_users=True)
            if not req_confirmed:
                return
            if pass_flag:
                await FishbowlBackend.send_embed(dest_user,
                                                 description="%s passed you %d scrap(s)!\n`%s`" % (source_user.mention,
                                                                                                   len(success_scraps),
                                                                                                   "`, `".join(success_scraps)),
                                                 footer=footer_msg)
            else:
                await FishbowlBackend.send_embed(source_user,
                                                 description="%s took %d scrap(s) from you:\n`%s`" % (dest_user.mention,
                                                                                                      len(success_scraps),
                                                                                                      "`, `".join(success_scraps)),
                                                 footer=footer_msg)
        else:
            req_confirmed = await confirm_req(ctx,
                                              target_user,
                                              ctx.author,
                                              "%s is trying to %s %d scraps %s %s! Accept?" % (ctx.author.mention,
                                                                                                keyword2[0],
                                                                                                len(scraps),
                                                                                                target_user.mention,
                                                                                                keyword2[1]),
                                              notify_users=False)
            if not req_confirmed:
                return
    else:
        descript = "%s %s... 0 scraps %s %s! Huh?" % (source_user.mention,
                                                      keyword1[0],
                                                      keyword1[1],
                                                      dest_user.mention)
    if fail_scraps:
        descript += "\nNote: Couldn't find `%s`!" % "`, `".join(fail_scraps)



    sessions[session_id]['players'][source_user.id] = source_hand
    sessions[session_id]['players'][dest_user.id] = dest_hand

    return await FishbowlBackend.send_embed(ctx, description=descript, footer=footer_msg)


@commands.command(name='pass')
@check_user_in_session()
async def pass_scrap(ctx, dest: str, scraps: commands.Greedy[clean_scrap]):
    return await pass_take(ctx, dest, scraps, pass_flag=True)


@pass_scrap.error
async def pass_err(ctx, error):
    #if isinstance(error, TimeoutError):
    #    print("hi2")
    #    return await FishbowlBackend.send_error(ctx, "Request timed out!")
    if isinstance(error, commands.MissingRequiredArgument):
        return await FishbowlBackend.send_error(ctx, "Missing an argument!\n"+
                                                "Give me both the player you're passing to and the scraps you're passing!")
    else:
        return await general_errors(ctx, error)


@commands.command(name='take')
@check_user_in_session()
async def take_scrap(ctx, dest: str, scraps: commands.Greedy[clean_scrap]):
    return await pass_take(ctx, dest, scraps, pass_flag=False)


@pass_scrap.error
async def pass_err(ctx, error):
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

    session_players = sessions[session_id]['players']
    [sessions[session_id]['bowl'].extend(session_players[k]) for k in session_players]
    sessions[session_id]['players'] = {k: [] for k in session_players}

    return await FishbowlBackend.send_embed(ctx,
                                            description="Recalling all hands back to the bowl!",
                                            footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))


@commands.command()
@check_user_in_session()
@check_creator()
async def shuffle(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]

    sessions[session_id]['bowl'].extend(sessions[session_id]['discard'])
    sessions[session_id]['discard'] = []

    return await FishbowlBackend.send_embed(ctx,
                                            description="Shuffling the discard pile back into the bowl!",
                                            footer="Bowl: %d (Session #%s)" % (len(sessions[session_id]['bowl']), session_id))


@commands.command(name="reset")
@check_user_in_session()
@check_creator()
async def reset_session(ctx, *args):
    user_id = ctx.author.id
    session_id = users[user_id]

    sessions[session_id]['bowl'] = []
    sessions[session_id]['discard'] = []
    sessions[session_id]['players'] = {k: [] for k in sessions[session_id]['players']}
    sessions[session_id]['total_scraps'] = 0

    return await FishbowlBackend.send_embed(ctx,
                                            description="Resetting session and destroying all scraps!",
                                            footer="Session #%s" % session_id)


@shuffle.error
@recall_hands.error
@reset_session.error
async def recall_error(ctx, error):
    if isinstance(error, CreatorOnly):
        return await FishbowlBackend.send_error(ctx, "Only the creator of the session can use this command!")
    else:
        return await general_errors(ctx, error)


@commands.command(name="help")
async def help_bot(ctx, keyword: clean_arg = ""):
    if not keyword:
        return await FishbowlBackend.send_message(ctx, "I'm **FishbowlBot**, a Discord bot for games where you put a bunch of scraps in a bowl/hat/etc. then take them out!\n\n" +
                                                  "Start a Fishbowl session with `start`, then have other players join in! Everyone can add scraps with `add`, then draw from the bowl using `draw`. You can also `edit` scraps, `pass` them to other players, and more!\n\n" +
                                                  "For a list of all commands, do `help commands`. You can also ask me for detailed help with a specific command. (i.e. `help start`)")
    if keyword in ["all", "commands", "command", "list"]:
        return await FishbowlBackend.send_embed(ctx, "", fields=bot_command_dict)
    if keyword in help_df.index:
        return await FishbowlBackend.send_message(ctx, "**%s**:\n" % help_df.loc[keyword]["CommandExample"] + help_df.loc[keyword]["DetailedHelp"])
    else:
        return await FishbowlBackend.send_error(ctx, "Don't recognize that help query! Try `help commands` for a list of all commands, or ask me for a specific command! (i.e. `help start`)")


def setup():
    bot_commands = [globals()[cmd] for cmd in help_df["Function"]]
    for bot_command in bot_commands:
        FishbowlBackend.bot.add_command(bot_command)



setup()
FishbowlBackend.bot.run(token)
