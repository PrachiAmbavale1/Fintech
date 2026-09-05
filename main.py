from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent import Orchestrator
from memory import PreferenceMemory
from scheduler import run_daily_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FinTech Intelligence Agent")
    p.add_argument("--run-now", action="store_true", help="Run the daily brief immediately")
    p.add_argument(
        "--schedule",
        action="store_true",
        help="Keep running and send the brief daily at config email_hour (default 09:00)",
    )
    p.add_argument("--demo", action="store_true", help="Use bundled sample articles (offline-friendly)")
    p.add_argument("--feedback", choices=["more", "less", "neutral"], help="Record explicit preference feedback")
    p.add_argument("--topic", type=str, help="Topic for feedback, e.g. 'artificial intelligence'")
    p.add_argument("--company", type=str, help="Company for feedback")
    p.add_argument("--config", type=str, default="config.yaml")
    p.add_argument(
        "--sync-calendar",
        action="store_true",
        help="Optional: create/update a Google Calendar daily reminder for the brief",
    )
    return p.parse_args()


def print_brief(brief) -> None:
    print("\n=== Daily Brief Ready ===")
    print(f"Subject : {brief.subject}")
    print(f"Stories : {len(brief.stories)}")
    print(f"Raw     : {brief.raw_count} | Relevant: {brief.relevant_count} | Rounds: {brief.search_rounds}")
    print(f"Timezone: {brief.timezone}")
    print("Output  : sample_email.html and data/runs/")
    print("\nStories:")
    for i, s in enumerate(brief.stories, 1):
        print(f"  {i}. [{s.publication}] {s.title}")
        print(f"     score={s.final_score:.2f}" if s.final_score is not None else "")


def run_once(args, memory: PreferenceMemory):
    orch = Orchestrator(config_path=args.config, memory=memory, use_sample=args.demo)
    brief = orch.run()
    print_brief(brief)
    return brief


def main() -> int:
    load_dotenv()
    setup_logging()
    args = parse_args()

    Path("data/runs").mkdir(parents=True, exist_ok=True)
    memory = PreferenceMemory("data/memory.db")

    if args.feedback:
        if not args.topic and not args.company:
            print("Provide --topic and/or --company with --feedback")
            return 2
        memory.apply_feedback(args.feedback, topic=args.topic, company=args.company)
        prefs = memory.load_preferences()
        print("Updated preferences:")
        for k, v in sorted(prefs.items(), key=lambda x: x[1], reverse=True)[:8]:
            print(f"  {k}: {v:.2f}")
        if not args.run_now and not args.schedule:
            return 0

    if args.sync_calendar:
        from calendar_tool import ensure_daily_brief_event

        ensure_daily_brief_event(args.config)

    if args.schedule:
        def job() -> None:
            run_once(args, memory)

        print(
            "Scheduler on - daily brief at "
            "settings.email_hour / settings.timezone from config.yaml"
        )
        print("Keep this terminal open (or run as a Windows service / Task Scheduler job).")
        print("Stop with Ctrl+C.\n")
        run_daily_scheduler(
            job,
            config_path=args.config,
            run_immediately=args.run_now,
        )
        return 0

    if not args.run_now and not args.feedback:
        args.run_now = True
        print("No flags given - running brief now. Use --demo for sample data.")

    if args.run_now:
        run_once(args, memory)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
