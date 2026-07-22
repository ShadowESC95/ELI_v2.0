-- Print-safe glyph substitution for the PDF build.
--
-- The markdown sources use emoji as section icons and as the 🟢/🟡/🔴 difficulty
-- tags. No text font (and no xelatex-compatible font at all — Noto Color Emoji is
-- a colour-bitmap format xelatex cannot embed) carries these, so they silently
-- vanished from the PDFs: "🟢 Anyone" printed as " Anyone", losing the tag's
-- meaning entirely.
--
-- Rather than strip the emoji from the sources (they read well on GitHub and in
-- the GUI), this filter runs at PDF build time only:
--   * meaning-bearing symbols become their words/ASCII equivalents,
--   * purely decorative section icons are dropped.
-- Applied via `--lua-filter` in scripts/generate_blueprint_pdfs.sh.

-- Meaning-bearing → explicit text (ASCII-safe: never swaps one missing glyph
-- for another).
local MEANING = {
  ["\u{1F7E2}"] = "[Everyone]",        -- green circle: no technical skill needed
  ["\u{1F7E1}"] = "[Some setup]",      -- yellow circle: a little technical
  ["\u{1F534}"] = "[Advanced]",        -- red circle: advanced
  ["\u{26A0}"]  = "Note:",             -- warning sign
  -- Used as trailing "this exists / is done" ticks in the blueprints. Kept as
  -- words, not ✓/✗: DejaVu Serif has no U+2713 either, so a symbol swap would
  -- just reintroduce the missing-glyph hole (verified, not assumed).
  ["\u{2705}"]  = "[done]",            -- white heavy check mark
  ["\u{2714}"]  = "[done]",            -- heavy check mark
  ["\u{2713}"]  = "[done]",            -- check mark
  ["\u{274C}"]  = "[no]",              -- cross mark
  ["\u{2717}"]  = "[no]",              -- ballot X
  ["\u{2605}"]  = "*",                 -- black star
  ["\u{2606}"]  = "*",
}

-- Everything else in the emoji/pictograph blocks is decorative: drop it.
local function is_decorative(cp)
  return (cp >= 0x1F300 and cp <= 0x1FAFF)   -- pictographs, symbols, extended-A
      or (cp >= 0x2600  and cp <= 0x27BF)    -- misc symbols + dingbats
      or (cp >= 0x1F000 and cp <= 0x1F0FF)
      or cp == 0xFE0F                        -- variation selector-16
      or cp == 0xFE0E
      or cp == 0x200D                        -- zero-width joiner
end

local function clean(s)
  local out = {}
  for _, cp in utf8.codes(s) do
    local ch = utf8.char(cp)
    local mapped = MEANING[ch]
    if mapped then
      out[#out + 1] = mapped
    elseif not is_decorative(cp) then
      out[#out + 1] = ch
    end
  end
  local result = table.concat(out)
  -- Collapse the double space left where a leading icon was removed.
  result = result:gsub("^%s+", ""):gsub("%s%s+", " ")
  return result
end

function Str(el)
  local cleaned = clean(el.text)
  if cleaned == "" then
    return {}          -- the whole token was an icon: remove it (and its space)
  end
  el.text = cleaned
  return el
end
