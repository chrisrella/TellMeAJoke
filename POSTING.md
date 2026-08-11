# Posting Pipeline

## What's set up

| Platform  | Status | Token expires |
|-----------|--------|---------------|
| Instagram | ✅ Working | ~60 days — re-run `facebook_auth.py` when it fails |
| Facebook  | ✅ Working | ~60 days — same token refresh |
| YouTube   | ✅ Working | Never (published OAuth app) |
| TikTok    | ⏳ Pending app review | Will need `tiktok_auth.py` once approved |


Question: How do I run the pipeline on a bunch of new clips
Let me check if batch.py already handles this:

Read batch.py
batch.py already does exactly this. It processes all approved clips that don't have a final video yet:


# See what would be processed
python3 caption-automation/batch.py --list

# Process all of them (pauses at ZapCap review for each)
python3 caption-automation/batch.py

# Process all, skip ZapCap review step
python3 caption-automation/batch.py --auto

# Process just 3 at a time
python3 caption-automation/batch.py --limit 3
Results land in output/ready_to_post/ automatically, ready for the next cron run.

PLAY A VIDEO WITH LOUD AUDIO:
ffplay -af "volume=4" "content/master/Nicole tells a snoop dogg joke.mp4"

## Daily workflow

**1. Run the full pipeline on a new clip** (blur → sticker → captions → generate caption)
```bash
python3 caption-automation/post_pipeline.py "Frank tells mexican joke.mp4" --theme mexican
```

**2. Post everything in the queue** (Instagram + Facebook + YouTube)
```bash
python3 caption-automation/poster.py --all
```

**3. Post just one video** (oldest in queue first)
```bash
python3 caption-automation/poster.py
```

---

## Automate with cron

Always use the full Python path so cron finds the right packages:
```
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
```

### Daily setup (do this each morning)

**1. Check what's queued:**
```bash
python3 caption-automation/poster.py --list
```

**2. Keep Mac awake for the posting window:**
```bash
caffeinate -t 21600 &   # 6 hours — kill it with: kill %1
```

**3. Open crontab:**
```bash
crontab -e
```

**4. In the vim editor that opens:**
- Type `:%d` + Enter to delete all existing lines
- Press `i` to enter insert mode
- Paste your new cron lines (see format below)
- Press Escape
- Type `:wq` + Enter to save and exit

**5. Verify it saved:**
```bash
crontab -l
```

### Cron line format

One video per hour from 12pm–4pm on August 4:
```cron    (COPY BELOW)
0 12 6 8 * cd /Users/chrisrella/TellMeAJoke && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 caption-automation/poster.py >> output/cron.log 2>&1
0 13 6 8 * cd /Users/chrisrella/TellMeAJoke && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 caption-automation/poster.py >> output/cron.log 2>&1
0 14 6 8 * cd /Users/chrisrella/TellMeAJoke && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 caption-automation/poster.py >> output/cron.log 2>&1
0 15 6 8 * cd /Users/chrisrella/TellMeAJoke && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 caption-automation/poster.py >> output/cron.log 2>&1
0 16 6 8 * cd /Users/chrisrella/TellMeAJoke && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 caption-automation/poster.py >> output/cron.log 2>&1
(END ABOVE)
```

Cron format: `0 <HOUR> <DAY> <MONTH> *`
- Hours are 24h (12=noon, 13=1pm, 18=6pm)
- Pinning day+month means the job only fires once, not every day

**Check the log after each post:**
```bash
cat output/cron.log
```

Check what's queued without posting:
```bash
python3 caption-automation/poster.py --list
python3 caption-automation/poster.py --dry-run
```

---

## Token refresh (when posting fails with auth error)

**Instagram / Facebook** — get a fresh short-lived token from [Graph API Explorer](https://developers.facebook.com/tools/explorer) (scopes: `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_read_user_content`), then:
```bash
python3 caption-automation/facebook_auth.py
```

**YouTube** — token never expires (no action needed).

**TikTok** — once app is approved:
```bash
python3 caption-automation/tiktok_auth.py   # one-time setup
python3 caption-automation/tiktok.py "clip.mp4" --private  # test first
python3 caption-automation/poster.py --all --tiktok         # then add to bulk posts
```

---

## Output folders

| Folder | Contents |
|--------|----------|
| `output/ready_to_post/` | Processed videos waiting to be posted |
| `output/already_posted/` | Archived after Instagram posts |
| `output/captions/` | Generated Instagram/TikTok captions |
| `output/post_log.txt` | Log of every successful post |
