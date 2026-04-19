# By Claude Sonnet 4.6 Adaptive
# April 18 2026

# pip install pandas requests

import pandas as pd
import requests
import math
import json

# ──────────────────────────── Data ──────────────────────────────
r = requests.get('https://raw.githubusercontent.com/Warzone2100/warzone2100/master/data/mp/stats/research.json')
df_original = pd.DataFrame.from_dict(r.json())

r = requests.get('https://raw.githubusercontent.com/Warzone2100/warzone2100/master/data/mp/stats/structure.json')
sdf = pd.DataFrame.from_dict(r.json())

# ───────────────────────── Constants ────────────────────────────
BASE_STARTING_TECHNOLOGIES = [
    'R-Sys-Spade1Mk1',        # Construction Unit
    'R-Vehicle-Body01',       # Light Body - Viper
    'R-Vehicle-Prop-Wheels',  # Wheeled Propulsion
]

UPGRADE_TECH_IDS = [
    None,
    'R-Struc-Research-Module',
    'R-Struc-Research-Upgrade01',
    'R-Struc-Research-Upgrade02',
    'R-Struc-Research-Upgrade03',
    'R-Struc-Research-Upgrade04',
    'R-Struc-Research-Upgrade05',
    'R-Struc-Research-Upgrade06',
    'R-Struc-Research-Upgrade07',
    'R-Struc-Research-Upgrade08',
    'R-Struc-Research-Upgrade09',
]

# Preset names and offsets mirror the game's research_offset script.
# The offset (in seconds) is the clean-start MRT threshold:
# techs that take <= offset seconds from a clean start are pre-researched.
PRESETS = [
    {'name': 'No Bases',                     'offset': 0},
    {'name': 'T1 with Bases',                'offset': 3 * 60},
    {'name': 'T1 with Advanced Bases',       'offset': int(6.4 * 60)},
    {'name': 'T2',                           'offset': 17 * 60},
    {'name': 'T3',                           'offset': 26 * 60},
]

# ───────────────── Pre-compute upgrade max rates ─────────────────
# These depend only on the structure stats, not on which techs are pre-researched.
base_rp   = sdf['A0ResearchFacility']['researchPoints']
module_rp = sdf['A0ResearchFacility']['moduleResearchPoints']

upgrade_max_rates = []
prev_rate = base_rp
for tid in UPGRADE_TECH_IDS:
    if tid is None:
        rate, max_rate = base_rp, base_rp
    elif tid == 'R-Struc-Research-Module':
        rate     = base_rp
        max_rate = base_rp + module_rp
    else:
        pct      = df_original[tid]['results'][0]['value'] / 100
        extra    = math.ceil(base_rp * pct)
        rate     = prev_rate + extra
        max_rate = rate + module_rp
    upgrade_max_rates.append(max_rate)
    prev_rate = rate

# ──────────────────────── Core functions ────────────────────────
def zero_out(df, tech):
    if tech not in df.columns:
        return
    df.at['researchPoints', tech] = 0
    reqs = df[tech]['requiredResearch']
    if isinstance(reqs, list):
        for child in reqs:
            zero_out(df, child)

def format_time(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f'{h}:{m:02}:{sec:02}' if h > 0 else f'{m}:{sec:02}'

def compute_preset(starting_techs_set):
    df = df_original.copy()
    for tech in starting_techs_set:
        zero_out(df, tech)

    # Memoised branch() scoped to this df snapshot
    memo = {}
    def branch(tech):
        if tech in memo:
            return memo[tech]
        if tech is None or tech not in df.columns:
            memo[tech] = 0
            return 0
        rp   = df.at['researchPoints', tech]
        reqs = df[tech]['requiredResearch']
        if not isinstance(reqs, list):
            memo[tech] = rp
            return rp
        child_max    = max((branch(c) for c in reqs), default=0)
        memo[tech]   = rp + child_max
        return memo[tech]

    inflection_points = [branch(t) for t in UPGRADE_TECH_IDS]

    # Find highest research-upgrade tech already in starting set
    starting_level = 0
    for i in range(len(UPGRADE_TECH_IDS) - 1, -1, -1):
        if UPGRADE_TECH_IDS[i] in starting_techs_set:
            starting_level = i
            break

    def calc_secs(points):
        if points <= 0:
            return 0
        lvl  = starting_level
        rate = upgrade_max_rates[lvl]
        done = secs = 0
        while done < points:
            if lvl < 10 and done > inflection_points[lvl + 1]:
                lvl  += 1
                rate  = upgrade_max_rates[lvl]
            done += rate
            secs += 1
        return secs

    rows = []
    for tech_id in df.columns:
        s = calc_secs(branch(tech_id))
        if s > 0:
            rows.append({
                'name': str(df[tech_id]['name']),
                'seconds': s,
                'time': format_time(s),
            })

    rows.sort(key=lambda x: (x['seconds'], x['name']))
    return rows

# ─────── Step 1: Clean-start MRT → figure out each preset's pre-researched techs ───────
print('Computing clean-start MRT...')

clean_df = df_original.copy()
for tech in BASE_STARTING_TECHNOLOGIES:
    zero_out(clean_df, tech)

clean_memo = {}
def clean_branch(tech):
    if tech in clean_memo:
        return clean_memo[tech]
    if tech is None or tech not in clean_df.columns:
        clean_memo[tech] = 0
        return 0
    rp   = clean_df.at['researchPoints', tech]
    reqs = clean_df[tech]['requiredResearch']
    if not isinstance(reqs, list):
        clean_memo[tech] = rp
        return rp
    child_max        = max((clean_branch(c) for c in reqs), default=0)
    clean_memo[tech] = rp + child_max
    return clean_memo[tech]

clean_inflections = [clean_branch(t) for t in UPGRADE_TECH_IDS]

def clean_calc(points):
    if points <= 0:
        return 0
    lvl  = 0
    rate = upgrade_max_rates[0]
    done = secs = 0
    while done < points:
        if lvl < 10 and done > clean_inflections[lvl + 1]:
            lvl  += 1
            rate  = upgrade_max_rates[lvl]
        done += rate
        secs += 1
    return secs

clean_secs = {tid: clean_calc(clean_branch(tid)) for tid in clean_df.columns}

# ─────────── Step 2: Compute MRT table for each preset ──────────
all_preset_data = []
for preset in PRESETS:
    print(f"  Computing: {preset['name']}...")
    offset = preset['offset']

    starting_techs = set(BASE_STARTING_TECHNOLOGIES)
    for tid, s in clean_secs.items():
        if 0 < s <= offset:
            starting_techs.add(tid)

    rows = compute_preset(starting_techs)
    all_preset_data.append({'name': preset['name'], 'rows': rows})

print('All presets done.')

# ──────────────────────── Generate HTML ─────────────────────────
preset_json   = json.dumps(all_preset_data, ensure_ascii=False)
default_preset = 2  # T1 Advanced Bases with Walls

options_html = '\n'.join(
    f'      <option value="{i}"{" selected" if i == default_preset else ""}>{p["name"]}</option>'
    for i, p in enumerate(PRESETS)
)

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Minimum Research Time</title>
  <style>
    body {{
      display: flex;
      flex-direction: column;
      align-items: center;
    }}
    table {{
      margin: 10px auto;
      border-collapse: collapse;
    }}
    thead th {{
      background: #f0f0f0;
      padding: 5px 10px;
      border-bottom: 2px solid black;
    }}
    thead th.r {{ text-align: right; }}
    thead th.l {{ text-align: left;  }}
    tbody tr:nth-child(odd)  td {{ background: #ffffff; }}
    tbody tr:nth-child(even) td {{ background: #f0f0f0; }}
    tbody tr:hover           td {{ background: #d1fff8; }}
    tbody td {{
      padding: 5px 10px;
    }}
    tbody td.r {{ text-align: right; }}
    tbody td.l {{ text-align: left;  }}
  </style>
</head>
<body>
  <h1>Warzone 2100 Minimum Research Time</h1>

  <select id="preset-select">{options_html}</select>

  <table>
    <thead>
      <tr>
        <th></th>
        <th class="l">Technology</th>
        <th class="r">Minimum Research Time</th>
      </tr>
    </thead>
    <tbody id="mrt-body"></tbody>
  </table>

  <script>
    const allData = {preset_json};

    function render() {{
      const idx     = +document.getElementById('preset-select').value;
      const rows    = allData[idx].rows;

      const frag = document.createDocumentFragment();
      rows.forEach((row, i) => {{
        const tr = document.createElement('tr');
        ['r', 'l', 'r'].forEach((cls, col) => {{
          const td = document.createElement('td');
          td.className = cls;
          td.textContent = col === 0 ? (i+1) : col === 1 ? row.name : row.time;
          tr.appendChild(td);
        }});
        frag.appendChild(tr);
      }});

      document.getElementById('mrt-body').replaceChildren(frag);
    }}

    document.getElementById('preset-select').addEventListener('change', render);
    render();
  </script>
</body>
</html>'''

with open('index.html', 'w') as f:
    f.write(html)

print('index.html written.')
