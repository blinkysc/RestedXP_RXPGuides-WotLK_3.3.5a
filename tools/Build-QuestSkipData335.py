#!/usr/bin/env python3
"""Build DB/wotlk/questSkip_335.lua from AzerothCore's quest tables.

Feeds the "Skip overleveled steps" option.

Usage:
    tools/Build-QuestSkipData335.py <azerothcore>/data/sql/base/db_world

Only quests that are safe to auto-skip once outleveled are emitted. A quest is left
out (and therefore never skipped) when it, or anything later in its chain:
  * is restricted to a class (AllowableClasses) or sits in a special quest
    category (negative QuestSortID: class, profession, holiday, ...),
  * teaches a spell or ability (RewardDisplaySpell, the client's "You will
    learn" line; RewardSpell alone is only a scripted cast on completion),
  * requires a profession skill (RequiredSkillID),
  * has a scaling or unknown level (QuestLevel <= 0).
Each emitted entry stores the quest's own level and the highest level found
anywhere later in its chain, so the runtime only skips a quest when the whole
remaining chain is far enough below the player too.

Quest-only items (StartItem / ItemDrop1-4) are mapped back to their quests so
a bare ".collect <item>" line can be skipped along with its quest. Every other
quest-class item (item_template class 12) is listed too, so the runtime can
skip it when every quest line in the same step is skipped; items tied to a
protected quest are left out of that list.
"""
import os
import sys

TEMPLATE_COLUMNS = 74   # every column before LogTitle (the first string)
ADDON_COLUMNS = 17

COL_ID, COL_LEVEL, COL_SORT = 0, 2, 4
COL_REWARD_NEXT, COL_DISPLAY_SPELL = 11, 15
COL_START_ITEM, COL_ITEM_DROPS = 19, (30, 32, 34, 36)
ADDON_CLASSES, ADDON_PREV, ADDON_NEXT, ADDON_SKILL = 2, 4, 5, 9


def numeric_rows(path, count):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("("):
                continue
            fields = line[1:].split(",", count)
            if len(fields) <= count - 1:
                continue
            try:
                # The last column of a row is followed by "),".
                yield [int(value.strip().rstrip("),;"))
                       for value in fields[:count]]
            except ValueError:
                continue


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    source = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        root, "DB", "wotlk", "questSkip_335.lua")

    level, protected, successors, item_quests = {}, set(), {}, {}

    def link(before, after):
        if before > 0 and after > 0 and before != after:
            successors.setdefault(before, set()).add(after)

    for row in numeric_rows(os.path.join(source, "quest_template.sql"),
                            TEMPLATE_COLUMNS):
        quest = row[COL_ID]
        level[quest] = row[COL_LEVEL]
        if (row[COL_LEVEL] <= 0 or row[COL_SORT] < 0 or
                row[COL_DISPLAY_SPELL]):
            protected.add(quest)
        link(quest, row[COL_REWARD_NEXT])
        for col in (COL_START_ITEM,) + COL_ITEM_DROPS:
            if row[col] > 0:
                item_quests.setdefault(row[col], set()).add(quest)

    for row in numeric_rows(os.path.join(source, "quest_template_addon.sql"),
                            ADDON_COLUMNS):
        quest = row[0]
        if row[ADDON_CLASSES] or row[ADDON_SKILL]:
            protected.add(quest)
        link(abs(row[ADDON_PREV]), quest)
        link(quest, abs(row[ADDON_NEXT]))

    if not level:
        sys.exit("No quest rows were parsed from " + source)

    # chain[q] = (highest level in q's chain, chain contains a protected quest)
    chain = {}

    def resolve(start):
        stack, on_stack = [(start, iter(successors.get(start, ())))], {start}
        best = {start: (level.get(start, 0), start in protected)}
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                on_stack.discard(node)
                chain[node] = best[node]
                if stack:
                    parent = stack[-1][0]
                    hi, prot = best[parent]
                    best[parent] = (max(hi, best[node][0]),
                                    prot or best[node][1])
                continue
            if child in chain:
                result = chain[child]
            elif child in on_stack:
                continue  # cycle: already accounted for higher up
            else:
                if child not in level:
                    continue
                best[child] = (level[child], child in protected)
                on_stack.add(child)
                stack.append((child, iter(successors.get(child, ()))))
                continue
            hi, prot = best[node]
            best[node] = (max(hi, result[0]), prot or result[1])

    for quest in level:
        if quest not in chain:
            resolve(quest)

    entries, skippable = [], set()
    for quest in sorted(level):
        hi, prot = chain[quest]
        if prot:
            continue
        skippable.add(quest)
        entries.append("%d=%d:%d" % (quest, level[quest], hi))

    # Only map items whose every quest is skippable; the runtime still checks
    # each of those quests against the player's level.
    items = []
    for item in sorted(item_quests):
        quests = item_quests[item]
        if quests <= skippable:
            items.append("i%d=%s" % (item, ",".join(map(str, sorted(quests)))))
    entries += items

    quest_class_items = set()
    for row in numeric_rows(os.path.join(source, "item_template.sql"), 2):
        if row[1] == 12:  # ITEM_CLASS_QUEST
            quest_class_items.add(row[0])
    # Items mapped above are handled by their quests; items tied to a
    # protected quest must never be skipped by step context.
    tied = set(item_quests)
    context_items = sorted(quest_class_items - tied)

    lines, line = [], ""
    for entry in entries:
        if len(line) + len(entry) > 150:
            lines.append(line)
            line = ""
        line += entry + ";"
    lines.append(line)

    with open(output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("""local _, addon = ...

-- Quests that "Skip overleveled steps" may skip once the player outlevels them.
-- Generated by tools/Build-QuestSkipData335.py from AzerothCore's
-- quest_template and quest_template_addon. Class, spell-reward, profession
-- and scaling quests -- and anything leading into one -- are left out, so
-- they are never skipped. Formats: id=questLevel:highestLevelInChain;
-- and i<itemId>=questId,... for quest-only items.
local encoded = [[
""")
        handle.write("\n".join(lines))
        handle.write("""
]]

-- Quest-class items with no known quest link: skipped only when every quest
-- line in the same step is skipped.
local contextItems = [[
""")
        ids, line = [], ""
        for item in context_items:
            if len(line) > 150:
                ids.append(line)
                line = ""
            line += "%d," % item
        ids.append(line)
        handle.write("\n".join(ids))
        handle.write("""
]]

local skippable, itemQuests = {}, {}
for questId, questLevel, chainLevel in
    string.gmatch(encoded, "(%d+)=(%d+):(%d+)") do
    skippable[tonumber(questId)] = {
        level = tonumber(questLevel), chainLevel = tonumber(chainLevel)
    }
end
for itemId, quests in string.gmatch(encoded, "i(%d+)=([%d,]+)") do
    local list = {}
    for questId in string.gmatch(quests, "%d+") do
        list[#list + 1] = tonumber(questId)
    end
    itemQuests[tonumber(itemId)] = list
end

local questItems = {}
for itemId in string.gmatch(contextItems, "%d+") do
    questItems[tonumber(itemId)] = true
end

addon.QuestSkipData335 = skippable
addon.QuestSkipItems335 = itemQuests
addon.QuestSkipContextItems335 = questItems
""")
    print("Wrote %d skippable quests (of %d), %d quest items and %d context "
          "items to %s" % (len(skippable), len(level), len(items),
                           len(context_items), output))


if __name__ == "__main__":
    main()
