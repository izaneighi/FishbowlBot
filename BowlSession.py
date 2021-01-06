import json

class BowlSession:
    def __init__(self, creatorID, dummy=False):
        self.creator = creatorID
        self.bowl_size = 0
        self.total_size = 0
        self.scrap_table = pd.DataFrame()
        self.scrap_table.columns = ["Entry", "Owner"]

    def size(self):
        return self.total_size, self.bowl_size

    def get_creator(self):
        return self.creator

    def set_creator(self, userID):
        self.creator = userID
        return self.creator

    def get_hand(self, userID):
        hand_list = self.scrap_table.loc[self.scrap_table["Owner"]==userID, "Entry"].tolist()
        return hand_list

    def add(self, scrap_list):
        num_scrap = len(scrap_list)
        self.total_size += num_scrap
        self.bowl_size += num_scrap
        added_rows = pd.DataFrame({"Entry": scrap_list, "Owner": [0]*num_scrap})
        #print(added_rows.head())
        self.scrap_table = self.scrap_table.append(added_rows,ignore_index=True)
        #print(self.scrap_table.tail())
        return

    def draw(self, userID, num_scraps=1):
        drawn_scraps = []
        while (len(drawn_scraps) < num_scraps) and (self.bowl_size > 0):
            drawn_ix = random.choice(self.scrap_table.loc[self.scrap_table["Owner"]==0].index)
            drawn_scraps.append(self.scrap_table.at[drawn_ix,"Entry"])
            self.scrap_table.at[drawn_ix,"Owner"] = userID
            self.bowl_size-=1
        return drawn_scraps

    def peek(self, num_scraps=1):
        drawn_scraps = []
        while len(drawn_scraps) < num_scraps:
            drawn_ix = random.choice(self.scrap_table.loc[self.scrap_table["Owner"]==0].index)
            drawn_scraps.append(self.scrap_table.at[drawn_ix,"Entry"])
        return

    def _find_scrap_index(self, entry, userID):
        verify_mask = (self.scrap_table["Owner"] == userID) & (self.scrap_table["Entry"] == entry)
        if not any(verify_mask):
            return -1
        return self.scrap_table.loc[verify_mask].index[0]

    def edit_scrap(self, oldWord, newWord, userID):
        scrap_ix = self._find_scrap_index(oldWord, userID)
        if (scrap_ix < 0):
            return 1
        self.scrap_table.at[scrap_ix, "Entry"] = newWord
        return 0

    def give_scrap_to_user(self, entry, giver, receiver):
        scrap_ix = self._find_scrap_index(entry, giver)
        if (scrap_ix < 0):
            return 1
        self.scrap_table.at[scrap_ix, "Owner"] = receiver
        return 0

    def take_scrap_from_user(self, taker, victim,entry=""):
        hand_df = self.scrap_table[self.scrap_table["Owner"] == victim]
        if len(hand_df.index) == 0:
            return 1 # 1: victim has no scraps in hand
        if not entry:
            taken_ix = random.choice(hand_df.index)
        else:
            taken_ix = self._find_scrap_index(entry,victim)
            if taken_ix < 0:
                return 2 # 2: scrap not found in victim's hand
        self.scrap_table.at[taken_ix, "Owner"] = taker
        return 0

    def reset_bowl(self):
        self.scrap_table["Owner"] = 0
        self.bowl_size = self.total_size
        return