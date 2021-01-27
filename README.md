# FishbowlBot
 A Discord bot to run games where you put a bunch of scraps in a bowl.
 
 Invite to your server [here](https://discord.com/api/oauth2/authorize?client_id=668525325973454848&permissions=2112&scope=bot).

### Dependencies
- `discord.py` (1.2+)
- `python-dotenv` (0.10+)
- `pandas`

### Commands
Default command prefix is `!`.

**Admin Commands:**
- `ban`: Bans a user from your session
- `bugreport`: Submit a bug report to the dev
- `changeprefix`: Change the prefix for the server
- `command`: Shows all commands.
- `end`: End your session 
- `help`: Get help for a command or list all commands
- `join`: Join Session #`ID`
- `leave`: Leave the session you're in
- `session`: Check session info
- `start`: Start a new session
- `unban`: Unbans a user from your session


**Play Commands:**
- `add`: Add `scrap` to the bowl 
- `addtohand`: Add `scrap` directly to your hand
- `check`: Check the number of scraps in play
- `destroy`: Destroy `scrap` in your hand
- `destroyhand`: Destroys your hand
- `draw`: Draw `#` scraps from the bowl, or specifically `scrap`
- `drawdiscard`: Draws from discard pile instead
- `edit`: Edit a scrap in your hand
- `empty`: Destroy scraps
- `hand`: Check your hand
- `pass`: Pass `player` `scrap` from your hand, or `#` random ones
- `peek`: Peek at `#` scraps from the bowl without removing them
- `play`: Play `scrap` from your hand
- `playhand`: Plays your entire hand
- `recall`: Recall all hands to the bowl 
- `return`: Return `scrap` in your hand to the bowl
- `returnhand`: Return your hand to the bowl
- `see`: List all scraps in the bowl or discard pile
- `show`: Show your hand to `player`
- `shuffle`: Shuffle the discard pile into the bowl 
- `take`: Take `scrap` from `player`'s hand, or `#` random ones