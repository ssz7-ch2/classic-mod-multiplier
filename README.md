## Setup

git clone with submodules

```
git clone --recurse-submodules https://github.com/ssz7-ch2/classic-mod-multiplier.git
```

Install requirements

```
pip install requirements.txt
```

## Usage

Specific replay on map

```
python run.py -l -b 1811527 -u 7562902
```

5 random replays from #30 to #60 on map

```
python run.py -s -b 1811527 --start 30 --end 60 --sample-size 5
```

10 random replays from the top 10 on 50 random maps (from beatmap_ids.json)

```
python run.py -s -c 50
```

All replays from folder

```
python run.py -s -f "C:/Users/abc/Downloads/Replays"
```

## Warning

The api endpoint for getting replays is expensive, so don't spam too many
replays.
