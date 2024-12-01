import os
import json
import random
import argparse
import sys
from typing import Iterable
from dotenv import load_dotenv
from ossapi import BeatmapsetSearchCategory, Ossapi, BeatmapsetSearchSort, Score
from time import sleep
from circleguard import Circleguard, Judgment, JudgmentType, ReplayCache, ReplayUnavailableException
from slider import Beatmap, Library, Slider, Spinner
from copy import deepcopy
from ossapi.models import NonLegacyMod

load_dotenv()

if not os.path.exists("library"):
  os.makedirs("library")

api = Ossapi(os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET"))
cg = Circleguard(os.getenv("API_KEY"), "circleguard.db")
library = Library("library")

def get_ranked_maps() -> list[int]:
  ranked_beatmap_ids = []
  cursor = None
  while True:
    res = api.search_beatmapsets(mode=0, explicit_content="show", sort=BeatmapsetSearchSort.RANKED_ASCENDING, cursor=cursor, category=BeatmapsetSearchCategory.RANKED)
    for beatmapset in res.beatmapsets:
      ranked_beatmap_ids += [beatmap.id for beatmap in beatmapset.beatmaps]

    if res.cursor is None:
      break
    cursor = res.cursor
    sleep(1)
  return ranked_beatmap_ids

def judgment_counts(judgments: Iterable[Judgment]):
  counts = {
    "count_300": 0,
    "count_100": 0,
    "count_50": 0,
    "count_miss": 0
  }

  for judgment in judgments:
    if judgment.type == JudgmentType.Hit300:
      counts["count_300"] += 1
    if judgment.type == JudgmentType.Hit100:
      counts["count_100"] += 1
    if judgment.type == JudgmentType.Hit50:
      counts["count_50"] += 1
    if judgment.type == JudgmentType.Miss:
      counts["count_miss"] += 1
  return counts

def object_count(beatmap: Beatmap):
  counts = {
    "sliderends": 0,
    "sliderticks": 0,
    "spinners": 0
  }
  for hit_obj in beatmap.hit_objects(circles=False, sliders=True, spinners=True):
    if isinstance(hit_obj, Slider):
      counts["sliderends"] += 1
      counts["sliderticks"] += hit_obj.ticks - 2
    if isinstance(hit_obj, Spinner):
      counts["spinners"] += 1
  return counts

def compute_total_score(count_300, count_100, count_50, count_miss, count_sliderends, max_sliderends, max_sliderticks, classic=False, combo_progress=1):
  sliderend_value = 10 if classic else 150
  max_base_score = (count_300 + count_100 + count_50 + count_miss) * 300 + max_sliderends * sliderend_value + max_sliderticks * 30
  base_score = count_300 * 300 + count_100 * 100 + count_50 * 50 + count_sliderends * sliderend_value + max_sliderticks * 30 # assume all sliderticks are hit
  acc_value = base_score / max_base_score

  return int(round(500000 * acc_value * combo_progress + 500000 * pow(acc_value, 5)))

def get_ranked_beatmap_ids(path):
  if os.path.isfile(path):
    with open(path, "r") as f:
      ranked_beatmap_ids = json.load(f)
    pass
  else:
    ranked_beatmap_ids = get_ranked_maps()
    with open(path, "w") as f:
      f.write(json.dumps(ranked_beatmap_ids))
  
  return ranked_beatmap_ids

def _run(replay, beatmap, beatmap_id, logging=False, save=True, combo_progress=None, stable_score=None):
  object_c = object_count(deepcopy(beatmap))

  judgments, classic_combo_progress = cg.judgments(replay, beatmap=deepcopy(beatmap), slider_acc=False)
  if combo_progress is not None:
    classic_combo_progress = combo_progress
  calculated = judgment_counts(judgments)

  # circleguard judgments doesn't include spinners, so we assume all spinners are 300s
  calculated["count_300"] += object_c["spinners"]

  # circleguard judgments counts sliderbreaks (due to missing slider head) as misses
  # so we can estimate the number of sliderbreaks by subtracting the replay.count_miss from the calculated misses
  sliderbreaks = calculated["count_miss"] - replay.count_miss

  # circleguard judgments does not include 100s from sliderends, but we can estimate it
  # the discrepancy between the replay.count_100 and calculated 100s is the missed_sliderends* + sliderbreaks
  # *these can also be due to missing sliderticks, but that rarely happens
  missed_sliderends = replay.count_100 - sliderbreaks - calculated["count_100"]

  if logging:
    print("sliderbreaks", sliderbreaks,"missed_sliderends", missed_sliderends)
    print("classic calculated", calculated)
    print("classic combo progress", classic_combo_progress)

  # number of sliderends hit
  count_sliderends = object_c["sliderends"] - missed_sliderends

  judgments, lazer_combo_progress = cg.judgments(replay, beatmap=deepcopy(beatmap), slider_acc=True)
  if combo_progress is not None:
    lazer_combo_progress = combo_progress
  calculated = judgment_counts(judgments)
  calculated["count_300"] += object_c["spinners"]
  if logging:
    print("lazer calculated", calculated)
    print("lazer combo progress", lazer_combo_progress)

  # slider heads in stable also count as a slidertick
  # sliderend count can be used here since # of sliderends == # of sliderheads
  total_sliderticks_classic = object_c["sliderticks"] + object_c["sliderends"]
  classic_total_score = compute_total_score(replay.count_300, replay.count_100, replay.count_50, replay.count_miss, count_sliderends, object_c["sliderends"], total_sliderticks_classic, classic=True, combo_progress=classic_combo_progress)
  total_score = compute_total_score(calculated["count_300"], calculated["count_100"], calculated["count_50"], calculated["count_miss"], count_sliderends, object_c["sliderends"], object_c["sliderticks"], combo_progress=lazer_combo_progress)

  if logging:
    print(f"\nlazer score:\t{total_score}")
    print(f"classic score:\t{classic_total_score}")
    if stable_score is not None:
      print(f"stable score:\t{stable_score}")
      print(f"ratio:\t\t{total_score / stable_score}")
    else:
      print(f"ratio:\t\t{total_score / classic_total_score}")

  # skip replays with incorrect misses due to issues with circleguard
  if missed_sliderends < 0 or sliderbreaks < 0:
    print("invalid replay")
    print("beatmap:", beatmap_id)
    print("user_id:", replay.user_id)
    return

  if save:
    with open("data.txt", "a") as f:
      if stable_score is not None:
        f.write(f"https://osu.ppy.sh/beatmaps/{beatmap_id}\t{replay.user_id}\t{stable_score}\t{classic_total_score}\t{total_score}\n")
      else:
        f.write(f"https://osu.ppy.sh/beatmaps/{beatmap_id}\t{replay.user_id}\t{classic_total_score}\t{total_score}\n")

def get_score_multiplier(mods: list[NonLegacyMod]):
  multiplier = 1.0
  for mod in mods:
    if mod.acronym == "CL":
      multiplier *= 0.96
    if mod.acronym == "HD":
      multiplier *= 1.06
    if mod.acronym == "HR":
      multiplier *= 1.06
    if mod.acronym == "DT" or mod.acronym == "NC":
      multiplier *= 1.10
    if mod.acronym == "FL":
      multiplier *= 1.12
    if mod.acronym == "HT":
      multiplier *= 0.3
    if mod.acronym == "NF":
      multiplier *= 0.5
    if mod.acronym == "EZ":
      multiplier *= 0.5
    if mod.acronym == "SO":
      multiplier *= 0.9
  return multiplier

def get_combo_progress_from_score(score: Score):
  return (score.total_score_without_mods - 500000 * pow(score.accuracy, 5)) / (500000 * score.accuracy)

def run(beatmap_ids=None, amount=1, start = 1, end=50, sample_size=10, logging=False, classic_lb=True, save=True, path="beatmap_ids.json", stable=False):
  if beatmap_ids is None:
    ranked_beatmap_ids = get_ranked_beatmap_ids(path)
    beatmap_ids = random.sample(ranked_beatmap_ids, min(amount, len(ranked_beatmap_ids)))

  for beatmap_id in beatmap_ids:
    beatmap_scores = [(score.user_id, score) for score in api.beatmap_scores(beatmap_id, mode="osu", legacy_only=classic_lb, limit=100).scores if score.legacy_score_id is not None][max(start - 1, 0):end]
    beatmap_scores = random.sample(beatmap_scores, min(sample_size, len(beatmap_scores)))

    beatmap = None
    for (user_id, score) in beatmap_scores:
      try:
        try:
          replay = ReplayCache("circleguard.db", beatmap_id, user_id)
          cg.load(replay)
          replay = replay.replay

          replay.count_300 = score.statistics.great if score.statistics.great is not None else 0
          replay.count_100 = score.statistics.ok if score.statistics.ok is not None else 0
          replay.count_50 = score.statistics.meh if score.statistics.meh is not None else 0
          replay.count_miss = score.statistics.miss if score.statistics.miss is not None else 0
        except:
          replay = cg.ReplayMap(beatmap_id, user_id)
        if beatmap is None:
          beatmap = replay.beatmap(library)

        combo_progress = None
        if stable:
          score.total_score_without_mods = int(round(score.total_score / get_score_multiplier(score.mods)))
          combo_progress = get_combo_progress_from_score(score)

        _run(replay, beatmap, beatmap_id, logging=logging, save=save, combo_progress=combo_progress, stable_score=score.total_score_without_mods)

        sleep(6)
      except ReplayUnavailableException:
        print("missing replay.", "beatmap:", beatmap_id, "user_id:", user_id)
      except KeyboardInterrupt:
        sys.exit()
        pass
      except:
        print("unable to process replay.", "beatmap:", beatmap_id, "user_id:", user_id)

def run_user(beatmap_id, user_id, logging=False, save=False, stable=False):
  replay = cg.ReplayMap(beatmap_id, user_id)
  beatmap = replay.beatmap(library)

  score = api.beatmap_user_score(beatmap_id, user_id, mode="osu", mods=replay.mods).score

  combo_progress = None
  score.total_score_without_mods = None
  if stable:
    score.total_score_without_mods = int(round(score.total_score / get_score_multiplier(score.mods)))
    combo_progress = get_combo_progress_from_score(score)

  _run(replay, beatmap, beatmap_id, logging=logging, save=save, combo_progress=combo_progress, stable_score=score.total_score_without_mods)

def run_folder(path, logging=False, save=False):
  replay_paths = [filename for filename in os.listdir(path) if filename.endswith("osr")]
  for replay_path in replay_paths:
    try:
      replay = cg.ReplayPath(os.path.join(path, replay_path))
      beatmap = replay.beatmap(library)

      if beatmap is None:
        print("unable to find beatmap.", "replay_path:", replay_path)
        continue

      _run(replay, beatmap, replay.beatmap_id, logging=logging, save=save)

      sleep(0.5)
    except KeyboardInterrupt:
      sys.exit()
      pass
    except:
      print("unable to process replay.", "replay_path:", replay_path)

def main():
  parser = argparse.ArgumentParser()

  parser.add_argument('-b', "--beatmap_ids", type=int, nargs='+')
  parser.add_argument('-c', "--count", type=int, default=1)
  parser.add_argument('-u', "--user_id", type=int)
  parser.add_argument('-f', "--folder", help="Scan through replays in the specified folder")
  parser.add_argument('-s', "--save", action=argparse.BooleanOptionalAction, default=False, help="Save data to file")
  parser.add_argument('-l', "--logging", action=argparse.BooleanOptionalAction, default=False)
  parser.add_argument('--start', type=int, default=1, help="The leaderboard spot to start from")
  parser.add_argument('--end', type=int, default=10, help="The leaderboard spot to end on")
  parser.add_argument('--sample-size', type=int, default=10, help="Amount of replays to use for each beatmap")
  parser.add_argument('--lazer-lb', action=argparse.BooleanOptionalAction, default=False, help="Use lazer leaderboard sorting")
  parser.add_argument('--stable', action=argparse.BooleanOptionalAction, default=False, help="Use stable's converted score")

  args = parser.parse_args()

  if args.user_id is not None and args.beatmap_ids is None:
    print("missing beatmap_id")
    return
  
  if args.user_id is not None:
    run_user(args.beatmap_ids[0], args.user_id, logging=args.logging, save=args.save, stable=args.stable)
    return
  
  if args.folder is not None:
    run_folder(args.folder, logging=args.logging, save=args.save)
    return
  
  run(beatmap_ids=args.beatmap_ids, amount=args.count, start=args.start, end=args.end, sample_size=args.sample_size, logging=args.logging, classic_lb=not args.lazer, save=args.save, stable=args.stable)

if __name__ == "__main__":
  main()