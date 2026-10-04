-- Run with tests/run.lua. Executes the real overleveled-quest helpers from
-- UI/GuideWindow.lua against the generated DB/wotlk/questSkip_335.lua.
-- ("Skip overleveled steps" option)
return function(root)
    local function read(path)
        local f = assert(io.open(root .. "/" .. path, "rb"))
        local text = f:read("*a"); f:close()
        return text:gsub("\r\n", "\n")
    end

    local addon = {game = "WOTLK", settings = {profile = {enableXpStepSkipping = true}}}
    local data = assert(loadfile(root .. "/DB/wotlk/questSkip_335.lua"))
    data(nil, addon)
    assert(next(addon.QuestSkipData335), "questSkip_335.lua produced no data")

    local level, log, equipped = 20, {}, {}
    local items = { -- name, link, quality, itemLevel, minLevel, ..., equipLoc
        [25873] = {"Keen Throwing Knife", nil, 1, 16, 11, nil, nil, nil, "INVTYPE_THROWN"},
        [2491] = {"Large Axe", nil, 1, 8, 3, nil, nil, nil, "INVTYPE_2HWEAPON"},
    }
    local env = setmetatable({
        UnitLevel = function() return level end,
        GetItemInfo = function(id) if items[id] then return unpack(items[id], 1, 9) end end,
        GetInventoryItemID = function(_, slot) return equipped[slot] end,
    }, {__index = _G})
    env._G = env
    addon.IsOnQuest = function(id) return log[id] ~= nil end
    addon.IsQuestComplete = function(id) return log[id] == "complete" end

    local source = read("UI/GuideWindow.lua")
    local block = assert(source:match(
        "\n(local levelSkipTags = .-)\nfunction addon%.UpdateStepCompletion%(%)"),
        "overleveled quest helpers not found")
    local chunk = assert(loadstring("local addon = ...\n" .. block))
    setfenv(chunk, env)
    chunk(addon)

    local skippable = addon.IsQuestOverleveled
    local VANQUISH, RUGA, PLAINSTRIDER = 784, 1823, 844

    assert(skippable(VANQUISH, "accept"), "low Durotar quest was not skipped")
    assert(not skippable(RUGA, "accept"), "class quest (Speak with Ruga) was skipped")
    for _, shaman in ipairs({1516, 1517}) do
        assert(not skippable(shaman, "accept"), "Shaman totem quest was skipped")
    end
    -- Chains come from quest_template_addon too: Skull Rock (827) unlocks
    -- Neeru Fireblade (829), whose chain reaches level 14.
    assert(addon.QuestSkipData335[827].chainLevel >= 14,
           "quest_template_addon chain links were not applied")
    assert(not skippable(PLAINSTRIDER, "accept"),
           "quest whose chain reaches the player's level (Plainstrider Menace) was skipped")
    assert(skippable(827, "accept"),
           "low chain that never reaches the player's level (Skull Rock) was kept")

    log[VANQUISH] = "complete"
    assert(skippable(VANQUISH, "turnin"), "finished low quest turn-in was kept")
    log[VANQUISH] = nil

    -- Vanquish the Betrayers is level 7 (chain 8): skipped from level 13 on.
    level = 12
    assert(not skippable(VANQUISH, "accept"), "quest under 5 levels below was skipped")
    level = 13
    assert(skippable(VANQUISH, "accept"), "quest 5 levels below was kept")
    level = 20

    addon.settings.profile.northrendLM = true
    assert(not skippable(VANQUISH, "accept"), "loremaster mode still skipped quests")
    addon.settings.profile.northrendLM = nil
    addon.settings.profile.enableXpStepSkipping = false
    assert(not skippable(VANQUISH, "accept"), "disabled option still skipped quests")
    addon.settings.profile.enableXpStepSkipping = true

    local accept = {tag = "accept", questId = VANQUISH}
    local step = {elements = {{tag = "goto", textOnly = true}, accept,
                              {tag = "target", textOnly = true}}}
    assert(addon.ApplyQuestLevelSkip(step) and accept.levelSkip,
           "grey-only step was not skipped")

    local train = {tag = "train"}
    step = {elements = {accept, train}}
    assert(not addon.ApplyQuestLevelSkip(step), "step with a trainer line was skipped")
    assert(accept.levelSkip, "grey line in a mixed step was not released")

    local class = {tag = "accept", questId = RUGA}
    step = {elements = {accept, class}}
    assert(not addon.ApplyQuestLevelSkip(step) and not class.levelSkip,
           "class quest in a mixed step was skipped")

    -- Bare ".collect" of a quest-only item (Tender Strider Meat -> Kyle's
    -- Gone Missing!) goes with its quest; ordinary items never do.
    local meat = {tag = "collect", id = 33009}
    step = {elements = {{tag = "goto", textOnly = true}, meat}}
    assert(addon.ApplyQuestLevelSkip(step), "quest-only item step was not skipped")
    -- A quest item with no direct quest link (Flawed Power Stone) follows the
    -- quest lines in its step, but never rescues a step that must stay.
    local stone = {tag = "collect", id = 4986}
    local stoneTurnin = {tag = "turnin", questId = 926}
    step = {elements = {stone, stoneTurnin}}
    assert(addon.ApplyQuestLevelSkip(step) and stone.levelSkip,
           "turn-in item step was not skipped with its quest")
    step = {elements = {stone, {tag = "turnin", questId = RUGA}}}
    assert(not addon.ApplyQuestLevelSkip(step) and not stone.levelSkip,
           "quest item was skipped next to a kept quest")
    step = {elements = {stone}}
    assert(not addon.ApplyQuestLevelSkip(step), "lone quest item step was skipped")

    -- Gear purchases: grey item and the slot is filled -> skip; empty -> keep.
    local knife = {tag = "collect", id = 25873}
    step = {elements = {{tag = "goto", textOnly = true}, knife}}
    assert(not addon.ApplyQuestLevelSkip(step), "first throwing weapon was skipped")
    equipped[18] = 1234
    assert(addon.ApplyQuestLevelSkip(step), "grey gear purchase was not skipped")
    level = 14
    assert(not addon.ApplyQuestLevelSkip(step), "gear near the player's level was skipped")
    level = 20
    local linen = {tag = "collect", id = 2589}
    step = {elements = {linen}}
    assert(not addon.ApplyQuestLevelSkip(step), "non-gear item step was skipped")

    -- The advance gate re-checks a step on its own; it must honour the skip
    -- or UpdateStepCompletion's advance is cancelled (step stays on screen).
    addon.services = {Register = function() end}
    assert(loadfile(root .. "/Guide/State.lua"))(nil, addon)
    local skippedAccept = {tag = "accept", questId = VANQUISH, levelSkip = true}
    step = {completed = true, completionFromElements = true, levelSkipped = true,
            elements = {{tag = "goto", textOnly = true}, skippedAccept}}
    assert(addon.guideState:CanAdvance(step), "advance gate rejected an overleveled step")
    step = {completed = true, completionFromElements = true,
            elements = {skippedAccept, {tag = "turnin", questId = 1}}}
    assert(not addon.guideState:CanAdvance(step), "advance gate ignored a required line")

    print("Overleveled quest skipping passed: class/spell/chain quests kept, quests 5+ levels below skipped.")
end
