-- Footnote markers in a passage's title and italic intro, as printed.
-- JSON: {"title": [{"n": 1, "at": 12}], "intro": [...]}, where "at" is a
-- character offset into stimuli.title / stimuli.intro. Markers inside the
-- numbered text are stored on each line in stimuli.lines ("notes").
ALTER TABLE stimuli ADD COLUMN marks TEXT;
