## Setup

1. git clone with submodules

```
git clone --recurse-submodules https://github.com/ssz7-ch2/classic-mod-multiplier.git
```

2. Install requirements

```
pip install -r requirements.txt
```

3. Place client id, client secret, and api v1 key in .env (follow the example in
   .env.example)

## Usage

Specific replay on map (`-l` is to print out info for the replay)

```
python run.py -l -b 1811527 -u 7562902
```

5 random replays from #30 to #60 on map (`-s` is to save info to file)

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
