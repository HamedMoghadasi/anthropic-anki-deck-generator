#!/usr/bin/env python3
"""
Finnish Anki Generator
======================
Generate A1-C2 Finnish example sentences for Anki cards.

Three modes:
  1. fill   — Take an existing Anki TSV export and fill in missing examples
  2. words  — Generate a fresh deck from a word list (one word per line)
  3. topic  — Generate a vocabulary deck on a topic (family, gym, work, etc.)

Usage:
  # Fill in missing examples in your existing Anki export
  python generate_examples.py fill input.txt --level A1 --examples 3

  # Generate from a word list
  python generate_examples.py words my_words.txt --level A2 --examples 3

  # Generate a topic-based vocabulary deck
  python generate_examples.py topic "family" --level A1 --count 30 --examples 3
  python generate_examples.py topic "gym, fitness, workout" --level B1 --count 50

Environment:
  ANTHROPIC_API_KEY must be set.

Output:
    Writes to ./output_<mode>_<timestamp>.txt in Anki TSV import format
    with 4 columns: word, meaning, example, example-meaning.
"""

import os
import sys
import json
import time
import argparse
import re
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic library not installed. Run: pip install anthropic")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

api_key = "<YOUR_API_KEY_HERE>"  # or set via ANTHROPIC_API_KEY env var
MODEL = "claude-sonnet-4-6"
FALLBACK_MODEL = "claude-haiku-4-5"
BATCH_SIZE = 20  # Words per API call
MAX_RETRIES = 3
RETRY_DELAY = 3  # seconds
OUTPUT_DIR = Path("words")

LEVEL_DESCRIPTIONS = {
    "A1": "absolute beginner — very simple sentences, present tense, basic vocabulary, 3-6 words per sentence",
    "A2": "beginner — simple sentences, present and past tense, everyday vocabulary, 4-8 words per sentence",
    "B1": "intermediate — varied tenses, slightly complex sentences, 6-12 words",
    "B2": "upper-intermediate — natural sentences with conjunctions and subordinate clauses",
    "C1": "advanced — nuanced sentences, idiomatic phrasing, complex grammar",
    "C2": "proficient — sophisticated and natural sentences as a native speaker would write",
}


# ============================================================================
# PROMPT BUILDING
# ============================================================================

def build_examples_prompt(words_with_meanings, level, num_examples):
    """Build the prompt for generating examples for a list of (word, meaning) pairs."""
    level_desc = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS["A2"])

    words_block = "\n".join(
        f"- {w}" + (f" ({m})" if m else "")
        for w, m in words_with_meanings
    )

    return f"""You are a Finnish language teacher creating Anki flashcards for a {level}-level learner.

For each Finnish word below, provide:
1. An English meaning (1-4 words, semicolon-separated if multiple senses)
2. Exactly {num_examples} Finnish example sentences
3. The English translation of each Finnish sentence

LEVEL: {level} — {level_desc}

Rules:
- Sentences must be natural Finnish that a {level} learner can understand and use.
- Use the target word naturally in each sentence (it doesn't need to be in nominative form).
- Keep vocabulary at the {level} level — don't introduce words harder than the target word.
- Vary the sentences (different subjects, contexts, grammatical forms).
- English translations should be natural English, not word-for-word.

OUTPUT FORMAT — strictly valid JSON, no markdown, no commentary:
{{
  "word1": {{
    "meaning": "english meaning",
    "examples": [
      {{"fi": "Finnish sentence.", "en": "English translation."}},
      {{"fi": "Finnish sentence.", "en": "English translation."}}
    ]
  }},
  "word2": {{ ... }}
}}

WORDS:
{words_block}

Respond with ONLY the JSON object."""


def build_topic_prompt(topic, level, count, num_examples):
    """Build the prompt for generating a topic-based vocabulary deck."""
    level_desc = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS["A2"])

    return f"""You are a Finnish language teacher creating an Anki vocabulary deck on a topic.

TOPIC: {topic}
LEVEL: {level} — {level_desc}
COUNT: {count} words

Generate exactly {count} Finnish words related to this topic, appropriate for a {level} learner.

For each word, provide:
1. The Finnish word (base form: infinitive for verbs, nominative singular for nouns)
2. English meaning (1-4 words)
3. Exactly {num_examples} Finnish example sentences with English translations

Rules:
- Choose words a {level} learner actually needs for this topic.
- Mix word types: nouns, verbs, adjectives, adverbs as appropriate.
- Order from most essential/frequent to less essential.
- No duplicates. No proper nouns unless central to the topic.
- Sentences must match the {level} level.

OUTPUT FORMAT — strictly valid JSON, no markdown:
{{
  "word1": {{
    "meaning": "english meaning",
    "examples": [
      {{"fi": "Finnish sentence.", "en": "English translation."}}
    ]
  }}
}}

Respond with ONLY the JSON object."""


# ============================================================================
# API CALL
# ============================================================================

def call_api(client, prompt, model=MODEL):
    """Call the Anthropic API and parse JSON response."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()

            # Strip markdown fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```\s*$", "", text)

            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            print(f"  [attempt {attempt+1}] JSON parse error: {e}")
            # Try the fallback model after first failure
            if attempt == 0 and model != FALLBACK_MODEL:
                print(f"  retrying with {FALLBACK_MODEL}...")
                model = FALLBACK_MODEL
        except Exception as e:
            last_err = e
            print(f"  [attempt {attempt+1}] API error: {e}")
            time.sleep(RETRY_DELAY)

    print(f"  FAILED after {MAX_RETRIES} attempts: {last_err}")
    return None


# ============================================================================
# BATCH PROCESSING
# ============================================================================

def generate_for_words(client, words_with_meanings, level, num_examples):
    """Process words in batches."""
    all_results = {}
    total = len(words_with_meanings)
    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = words_with_meanings[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"Batch {batch_num}/{num_batches} ({len(batch)} words)...", flush=True)

        prompt = build_examples_prompt(batch, level, num_examples)
        result = call_api(client, prompt)
        if result:
            all_results.update(result)
            print(f"  ✓ got {len(result)} words")
        else:
            print(f"  ✗ batch failed, continuing...")

        # Light rate-limiting
        if batch_num < num_batches:
            time.sleep(1)

    return all_results


def generate_topic(client, topic, level, count, num_examples):
    """Generate a topic-based deck. May need multiple calls if count is large."""
    all_results = {}
    per_call = min(count, 30)  # Cap per call to keep responses reliable
    remaining = count

    call_num = 1
    while remaining > 0:
        this_count = min(per_call, remaining)
        print(f"Topic call {call_num} — generating {this_count} words on '{topic}'...", flush=True)

        existing_note = ""
        if all_results:
            existing = ", ".join(list(all_results.keys())[-30:])
            existing_note = f"\n\nDO NOT repeat any of these already-generated words: {existing}"

        prompt = build_topic_prompt(topic, level, this_count, num_examples) + existing_note
        result = call_api(client, prompt)

        if result:
            # Dedupe in case the model repeats
            new_words = {k: v for k, v in result.items() if k not in all_results}
            all_results.update(new_words)
            print(f"  ✓ got {len(new_words)} new words (total: {len(all_results)})")
            remaining -= len(new_words)
            if not new_words:
                print("  no new words — stopping")
                break
        else:
            print(f"  ✗ call failed, stopping")
            break

        call_num += 1
        if call_num > 10:
            print("  reached max calls, stopping")
            break
        time.sleep(1)

    return all_results


# ============================================================================
# INPUT PARSING
# ============================================================================

def parse_anki_export(path):
    """Parse Anki TSV export. Supports legacy 2-column and 4-column formats."""
    with open(path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    header_lines = [l for l in raw_lines if l.startswith("#")]
    data_lines = [l.rstrip("\n") for l in raw_lines if not l.startswith("#") and l.strip()]

    cards = []
    for line in data_lines:
        if "\t" not in line:
            continue

        parts = [p.strip().strip('"') for p in line.split("\t")]

        # New format: word<TAB>meaning<TAB>example<TAB>example-meaning
        if len(parts) >= 4:
            word = parts[0]
            meaning = parts[1]
            fi_text = parts[2]
            english = parts[3]
        else:
            # Legacy format: front<TAB>back
            tab_idx = line.index("\t")
            front = line[:tab_idx].strip()
            back_raw = line[tab_idx + 1 :].strip().strip('"')

            word = front.split()[0] if front.split() else ""
            fi_text = front[len(word):].strip()

            back_tabs = back_raw.split("\t")
            first_part = back_tabs[0].strip()

            meaning_match = re.search(r"\s{10,}(\S.+)$", first_part)
            meaning = meaning_match.group(1).strip() if meaning_match else ""

            english = ""
            for p in reversed(back_tabs[1:]):
                p = p.strip()
                if p and len(p) > 5:
                    english = p
                    break

        has_fi = bool(fi_text and len(fi_text) > 5)
        has_eng = bool(english and len(english) > 5)

        cards.append({
            "word": word,
            "meaning": meaning,
            "fi_examples": fi_text if has_fi else "",
            "english_examples": english if has_eng else "",
            "has_fi": has_fi,
            "has_eng": has_eng,
        })

    return header_lines, cards


def parse_word_list(path):
    """Parse a plain word list. Supports 'word' or 'word|meaning' format."""
    words = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                w, m = line.split("|", 1)
                words.append((w.strip(), m.strip()))
            elif "\t" in line:
                w, m = line.split("\t", 1)
                words.append((w.strip(), m.strip()))
            else:
                words.append((line, ""))
    return words


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================

def format_anki_line(word, meaning, examples, tags=None):
    """
    Build a single Anki TSV line.

    Default format:
    word<TAB>meaning<TAB>example<TAB>example-meaning

    Topic mode format (when tags is provided):
    word<TAB>meaning<TAB>example<TAB>example-meaning<TAB>tags

    Examples are joined with <br> so multiple examples fit into one field.
    This makes Anki field mapping straightforward for note types that have
    separate word/meaning/example/example-meaning fields.
    """
    # Build numbered example lines with <br> for line breaks inside one field
    example_fi = "<br>".join(f"{i+1}. {ex['fi']}" for i, ex in enumerate(examples))
    example_en = "<br>".join(f"{i+1}. {ex['en']}" for i, ex in enumerate(examples))

    fields = [word, meaning, example_fi, example_en]
    if tags is not None:
        fields.append(tags)
    # Strip any stray tabs/newlines inside fields (TSV safety)
    fields = [f.replace("\t", " ").replace("\n", " ").replace("\r", "") for f in fields]

    return "\t".join(fields)


def write_output(out_path, header_lines, lines):
    """Write the final TSV file."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        # Standard Anki headers — always emit these to be safe
        f.write("#separator:tab\n")
        f.write("#html:true\n")
        for line in lines:
            f.write(line + "\n")


# ============================================================================
# MAIN MODES
# ============================================================================

def mode_fill(args, client):
    """Fill in missing examples in an existing Anki export."""
    print(f"Reading {args.input}...")
    header_lines, cards = parse_anki_export(args.input)
    print(f"  Found {len(cards)} cards")

    needs_work = [(c["word"], c["meaning"]) for c in cards if not c["has_eng"]]
    seen = set()
    needs_unique = []
    for w, m in needs_work:
        if w not in seen:
            seen.add(w)
            needs_unique.append((w, m))

    print(f"  {len(needs_unique)} unique words need examples")

    if not needs_unique:
        print("Nothing to do.")
        return

    if args.limit:
        needs_unique = needs_unique[: args.limit]
        print(f"  Limited to first {len(needs_unique)} words (--limit)")

    print(f"\nGenerating {args.examples} examples per word at level {args.level}...\n")
    results = generate_for_words(client, needs_unique, args.level, args.examples)
    print(f"\nDone — got examples for {len(results)} words")

    # Build output: keep complete cards as-is (re-split into clean fi/en pairs),
    # and add newly-generated examples for incomplete ones.
    out_lines = []
    seen_words = set()
    for c in cards:
        if c["word"] in seen_words:
            continue
        seen_words.add(c["word"])

        if c["has_eng"]:
            # Re-split the existing fi/en text into matched sentence pairs.
            # Finnish examples are space-separated; English ones are run-together
            # but each ends with . ! or ?
            fi_parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", c["fi_examples"]) if s.strip()]
            en_parts = [s.strip() for s in re.split(r"(?<=[.!?])\s*(?=[A-Z])", c["english_examples"]) if s.strip()]
            # If counts don't match, just zip what we have (the extras get dropped)
            pairs = [{"fi": fi, "en": en} for fi, en in zip(fi_parts, en_parts)]
            if pairs:
                line = format_anki_line(c["word"], c["meaning"], pairs)
                out_lines.append(line)
        elif c["word"] in results:
            r = results[c["word"]]
            meaning = r.get("meaning", c["meaning"])
            examples = r.get("examples", [])
            if examples:
                line = format_anki_line(c["word"], meaning, examples)
                out_lines.append(line)

    out_path = str(OUTPUT_DIR / f"output_fill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    write_output(out_path, header_lines, out_lines)
    print(f"\nWrote {len(out_lines)} cards to {out_path}")


def mode_words(args, client):
    """Generate from a word list."""
    print(f"Reading word list {args.input}...")
    words = parse_word_list(args.input)
    print(f"  Found {len(words)} words")

    if args.limit:
        words = words[: args.limit]
        print(f"  Limited to first {len(words)} words")

    print(f"\nGenerating {args.examples} examples per word at level {args.level}...\n")
    results = generate_for_words(client, words, args.level, args.examples)
    print(f"\nDone — got examples for {len(results)} words")

    out_lines = []
    for word, _ in words:
        if word in results:
            r = results[word]
            line = format_anki_line(word, r.get("meaning", ""), r.get("examples", []))
            out_lines.append(line)

    out_path = str(OUTPUT_DIR / f"output_words_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    write_output(out_path, None, out_lines)
    print(f"\nWrote {len(out_lines)} cards to {out_path}")


def mode_topic(args, client):
    """Generate a topic-based vocabulary deck."""
    print(f"Topic: {args.topic}")
    print(f"Level: {args.level}, Count: {args.count}, Examples per word: {args.examples}\n")

    results = generate_topic(client, args.topic, args.level, args.count, args.examples)
    print(f"\nDone — got {len(results)} words")

    out_lines = []
    # Build stable tags from the topic string for Anki import mapping.
    topic_tags = " ".join(
        f"topic::{t}"
        for t in [re.sub(r"[^a-zA-Z0-9]+", "_", p.strip().lower()).strip("_") for p in args.topic.split(",")]
        if t
    )
    if not topic_tags:
        topic_tags = "topic::generated"

    for word, data in results.items():
        line = format_anki_line(word, data.get("meaning", ""), data.get("examples", []), tags=topic_tags)
        out_lines.append(line)

    safe_topic = re.sub(r"[^a-zA-Z0-9]+", "_", args.topic)[:30]
    out_path = str(OUTPUT_DIR / f"output_topic_{safe_topic}_{args.level}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    write_output(out_path, None, out_lines)
    print(f"\nWrote {len(out_lines)} cards to {out_path}")


# ============================================================================
# CLI
# ============================================================================

def main():
    p = argparse.ArgumentParser(
        description="Generate Finnish Anki cards with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="mode", required=True)

    # fill
    pf = sub.add_parser("fill", help="Fill missing examples in an Anki TSV export")
    pf.add_argument("input", help="Path to your Anki TSV export")
    pf.add_argument("--level", default="A1", choices=list(LEVEL_DESCRIPTIONS.keys()))
    pf.add_argument("--examples", type=int, default=3, help="Examples per word (default 3)")
    pf.add_argument("--limit", type=int, help="Only process N words (for testing)")

    # words
    pw = sub.add_parser("words", help="Generate from a word list file")
    pw.add_argument("input", help="Path to word list (one word per line, optionally 'word|meaning')")
    pw.add_argument("--level", default="A1", choices=list(LEVEL_DESCRIPTIONS.keys()))
    pw.add_argument("--examples", type=int, default=3)
    pw.add_argument("--limit", type=int)

    # topic
    pt = sub.add_parser("topic", help="Generate a topic-based vocabulary deck")
    pt.add_argument("topic", help="Topic, e.g. 'family' or 'gym, fitness, workout'")
    pt.add_argument("--level", default="A1", choices=list(LEVEL_DESCRIPTIONS.keys()))
    pt.add_argument("--count", type=int, default=30, help="Number of words to generate")
    pt.add_argument("--examples", type=int, default=3)

    args = p.parse_args()

    if not api_key:
        print("ERROR: set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if args.mode == "fill":
        mode_fill(args, client)
    elif args.mode == "words":
        mode_words(args, client)
    elif args.mode == "topic":
        mode_topic(args, client)


if __name__ == "__main__":
    main()