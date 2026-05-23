#!/usr/bin/env python3
"""
Batch topic runner for the Finnish Anki Generator.

Reads a topics file line by line, runs `generate_examples.py topic ...` for each,
moves outputs into a folder, then merges everything into one deduplicated deck.

Topics file format:
  - One topic per line.
  - Blank lines and lines starting with # are skipped.
  - Optional per-line count override with "topic | count":
        family, relatives | 35
        colors | 20
  - If no count is given, --default-count is used.

Usage:
  python run_topics.py topics.txt --level A1
  python run_topics.py topics.txt --level B1 --default-count 40 --examples 3
  python run_topics.py topics.txt --level A2 --dry-run     # preview without calling API
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import re
from datetime import datetime
from pathlib import Path


def parse_topics_file(path):
    """Yield (topic, count_override_or_None) for each non-empty, non-comment line."""
    topics = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                topic, count_str = line.split("|", 1)
                topic = topic.strip()
                try:
                    count = int(count_str.strip())
                except ValueError:
                    print(f"  WARNING: bad count on line '{line}', using default")
                    count = None
            else:
                topic = line
                count = None
            topics.append((topic, count))
    return topics


def find_generator_script():
    """Locate generate_examples.py — same directory as this script, then CWD."""
    here = Path(__file__).parent / "generate_examples.py"
    if here.exists():
        return str(here)
    cwd = Path.cwd() / "generate_examples.py"
    if cwd.exists():
        return str(cwd)
    print("ERROR: generate_examples.py not found next to this script or in current directory")
    sys.exit(1)


def snapshot_output_files():
    """Return the set of output_topic_*.txt files currently in CWD."""
    return set(p.name for p in Path.cwd().glob("output_topic_*.txt"))


def run_topic(generator, topic, level, count, examples, python_cmd):
    """Invoke generate_examples.py for a single topic. Returns True on success."""
    cmd = [
        python_cmd, generator, "topic", topic,
        "--level", level,
        "--count", str(count),
        "--examples", str(examples),
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def extract_word_from_line(line):
    """Pull the lowercase word out of a TSV line whose front field is <b>word</b>...."""
    m = re.search(r"<b>([^<]+)</b>", line)
    if m:
        return m.group(1).strip().lower()
    # Fallback: first token of the front field, with HTML stripped
    front = line.split("\t", 1)[0]
    cleaned = re.sub(r"<[^>]+>", "", front).strip()
    return cleaned.split()[0].lower() if cleaned else None


def merge_outputs(output_dir, merged_path):
    """Concatenate all TSVs in output_dir, deduping by word (case-insensitive)."""
    seen_words = {}      # lowercase_word -> source filename
    total_cards = 0
    duplicates = 0
    duplicate_examples = []  # Keep a few to show in the summary

    with open(merged_path, "w", encoding="utf-8") as out:
        out.write("#separator:tab\n")
        out.write("#html:true\n")

        for tsv_file in sorted(output_dir.glob("*.txt")):
            with open(tsv_file, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.rstrip("\n")
                    if not line.strip() or line.startswith("#"):
                        continue

                    word = extract_word_from_line(line)
                    if not word:
                        continue

                    if word in seen_words:
                        duplicates += 1
                        if len(duplicate_examples) < 5:
                            duplicate_examples.append(
                                f"'{word}' (already in {seen_words[word]}, also in {tsv_file.name})"
                            )
                    else:
                        seen_words[word] = tsv_file.name
                        out.write(line + "\n")
                        total_cards += 1

    return total_cards, duplicates, duplicate_examples


def main():
    parser = argparse.ArgumentParser(
        description="Batch-generate Anki topic decks from a topics file"
    )
    parser.add_argument("topics_file", help="Path to a text file with one topic per line")
    parser.add_argument(
        "--level", default="A1",
        choices=["A1", "A2", "B1", "B2", "C1", "C2"],
        help="CEFR level for all topics (default A1)"
    )
    parser.add_argument(
        "--default-count", type=int, default=30,
        help="Words per topic when not overridden in the file (default 30)"
    )
    parser.add_argument(
        "--examples", type=int, default=3,
        help="Examples per word (default 3)"
    )
    parser.add_argument(
        "--python", default=None,
        help="Python command to invoke (default: auto-detect 'py' on Windows, else 'python3')"
    )
    parser.add_argument(
        "--sleep", type=float, default=2.0,
        help="Seconds to wait between topics (default 2)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan without running anything"
    )
    args = parser.parse_args()

    # Resolve python command
    if args.python:
        python_cmd = args.python
    else:
        python_cmd = "py" if os.name == "nt" else "python3"

    # Parse topics
    if not Path(args.topics_file).exists():
        print(f"ERROR: topics file not found: {args.topics_file}")
        sys.exit(1)

    topics = parse_topics_file(args.topics_file)
    if not topics:
        print("ERROR: no topics found in file")
        sys.exit(1)

    # Find the generator script
    generator = find_generator_script()
    print(f"Generator: {generator}")
    print(f"Level: {args.level}")
    print(f"Default count: {args.default_count} words/topic")
    print(f"Examples per word: {args.examples}")
    print(f"Topics to process: {len(topics)}")
    total_words = sum(c if c else args.default_count for _, c in topics)
    print(f"Approximate total words: {total_words}\n")

    if args.dry_run:
        print("DRY RUN — would generate:")
        for i, (topic, count) in enumerate(topics, 1):
            c = count if count else args.default_count
            print(f"  [{i:3d}] {topic} (count={c})")
        return

    # Output directory for per-topic files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"topics_{args.level}_{timestamp}")
    output_dir.mkdir(exist_ok=True)
    print(f"Output folder: {output_dir}\n")

    # Run each topic
    succeeded = []
    failed = []
    start = time.time()

    for i, (topic, count) in enumerate(topics, 1):
        c = count if count else args.default_count
        print("=" * 70)
        print(f"[{i}/{len(topics)}] {topic}  (count={c})")
        print("=" * 70)

        before = snapshot_output_files()
        ok = run_topic(generator, topic, args.level, c, args.examples, python_cmd)
        after = snapshot_output_files()
        new_files = after - before

        if ok and new_files:
            # Move the newly-created files into the output folder
            for fname in new_files:
                src = Path(fname)
                dst = output_dir / fname
                shutil.move(str(src), str(dst))
                print(f"  Saved -> {dst}")
            succeeded.append(topic)
        else:
            print(f"  X Failed")
            failed.append(topic)

        if i < len(topics):
            time.sleep(args.sleep)

    # Summary
    duration = int(time.time() - start)
    mins, secs = divmod(duration, 60)
    print("\n" + "=" * 70)
    print("RUN SUMMARY")
    print("=" * 70)
    print(f"Succeeded: {len(succeeded)} / {len(topics)}")
    print(f"Duration:  {mins}m {secs}s")
    if failed:
        print("\nFailed topics:")
        for t in failed:
            print(f"  - {t}")

    # Merge step
    print("\nMerging all generated files into one deduplicated deck...")
    merged_path = output_dir.parent / f"merged_{args.level}_{timestamp}.txt"
    total_cards, duplicates, dupe_examples = merge_outputs(output_dir, merged_path)

    print(f"\nMerged deck ready: {merged_path}")
    print(f"  Unique cards:      {total_cards}")
    print(f"  Duplicates skipped: {duplicates}")
    if dupe_examples:
        print("  Examples of duplicates:")
        for d in dupe_examples:
            print(f"    - {d}")

    print("\nImport into Anki:")
    print(f"  1. Anki -> File -> Import")
    print(f"  2. Pick: {merged_path}")
    print(f"  3. Make sure 'Allow HTML in fields' is ON")
    print(f"  4. Map field 1 -> Front, field 2 -> Back")


if __name__ == "__main__":
    main()
