# Finnish Anki Generator

A reusable tool for generating Finnish Anki flashcards with AI. Three modes:

1. **fill** — Fill missing examples in an existing Anki TSV export
2. **words** — Generate examples for a custom word list
3. **topic** — Generate a topic-based vocabulary deck from scratch

## Setup

```bash
# 1. Install the Anthropic SDK
pip install anthropic

# 2. Get an API key from https://console.anthropic.com/
#    Add credits ($5 is plenty for a long time)

# 3. Set the key (add to ~/.bashrc to make it permanent)
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Usage

### Mode 1: Fill missing examples in your existing Anki export

```bash
python generate_examples.py fill Finnish_words_-_A1.txt --level A1 --examples 3
```

This reads your TSV, finds cards missing English examples, generates them, and writes a new TSV with everything filled in.

Options:
- `--level A1|A2|B1|B2|C1|C2` (default A1)
- `--examples N` how many examples per word (default 3)
- `--limit N` only process first N words (useful for testing first)

### Mode 2: Generate from a word list

Create `my_words.txt`:
```
kahvi
ruoka|food
juoda|to drink
```

Then:
```bash
python generate_examples.py words my_words.txt --level A2 --examples 3
```

The meaning after `|` is optional — the AI will fill it in if missing.

### Mode 3: Generate a topic-based deck

```bash
# Family vocabulary at A1
python generate_examples.py topic "family" --level A1 --count 30

# Gym words at B1
python generate_examples.py topic "gym, fitness, workout, exercise" --level B1 --count 50

# Multiple topics
python generate_examples.py topic "shopping, groceries, prices" --level A2 --count 40
```

Options:
- `--count N` how many words to generate (default 30; large counts split into multiple API calls)
- `--level` and `--examples` as above

## Output

`fill` and `words` modes write tab-separated files under `words/` with 4 columns:

1. word
2. meaning
3. example
4. example-meaning

`topic` mode writes files under `words/` with 5 columns (adds `tags`):

1. word
2. meaning
3. example
4. example-meaning
5. tags

Import into Anki:

1. Anki → File → Import
2. Pick the output file
3. Use your existing note type
4. Map fields:
	- word → 1
	- meaning → 2
	- example → 3
	- example-meaning → 4
	- Tags → 5 (for `topic` mode) or (Nothing) for `fill`/`words`

## Cost

Each batch of 20 words uses roughly 2-4K tokens. With current Anthropic pricing:
- Filling 800 missing examples (A1 deck): ~$1-2
- Generating a 50-word topic deck: ~$0.10-0.20

You can switch the `MODEL` constant near the top of the script to `claude-sonnet-4-5` for ~5x cheaper output at slightly lower quality (still excellent for language tasks).

## First-time test

```bash
# Tiny test run to verify everything works (3 words, ~5 seconds, $0.01)
python generate_examples.py topic "coffee" --level A1 --count 5
```

If that produces `output_topic_coffee_A1_*.txt` with 5 cards, you're good to run the big jobs.
