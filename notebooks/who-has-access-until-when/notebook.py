# %% [markdown]
# # Who has access, and until when
# Read which projects you reach and when your access to each ends, then (as a project administrator) who has access to
# this project, through what, and the last day each person's access lasts. Nothing here changes anyone's access: end
# dates are set and extended on the project page in the Workspace, or with the documented operations the guide
# "Running a project" shows.
#
# **Install once.** Put this notebook and the `requirements.txt` published beside it in an empty folder, then run:
#
#     python -m venv .venv
#     . .venv/bin/activate              # Windows: .venv\Scripts\activate
#     pip install -r requirements.txt
#     python -m ipykernel install --user --name ophiolite-gallery
#
# Open the notebook with the `ophiolite-gallery` kernel. Without `OPHIOLITE_URL` it works on a synthetic project served
# on your own computer; nothing real is read. To read your project, put the `configuration.json` from Connect → Use
# Python in this folder and run `ophiolite login` here (or `ophiolite login --key-stdin` to paste a project access key);
# then set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT` to the address and project it names before you start Jupyter.
# %%
from datetime import date, datetime, timedelta, timezone
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ophiolite.account import connect as account_for
from ophiolite.gallery import connect

client = connect()
account = account_for(client.url, client.credential, client.http)


def last_day(instant):
    """The last day access lasts, for a stored end: the end is the start of the next day in UTC, so the last day is
    the UTC date just before it, wherever you are (2027-01-01T00:00:00Z: 31 December 2026)."""
    at = datetime.fromisoformat(instant.replace('Z', '+00:00'))
    return (at.astimezone(timezone.utc) - timedelta(microseconds=1)).date()


def words(day):
    return f'{day.day} {day:%B} {day.year}'
# %% [markdown]
# ## Your projects, and until when
# Each row from `projects()` carries `access_ends_at`: the instant your access ends, or `None` when it does not end
# (no end date, or a team also gives you access). A project whose access already ended is not listed; the Workspace
# says so when you open it.
# %%
mine = account.projects()
for row in mine:
    until = 'no end date' if row['access_ends_at'] is None else 'ends ' + words(last_day(row['access_ends_at']))
    print(f"{row['name'] or 'Unnamed project'} ({row['role']}): {until}")
assert all('access_ends_at' in row for row in mine)
# %% [markdown]
# ## Who has access to this project
# Project administrators can read everyone's access with the documented operation `access/effective`. Each person has
# one row: whether they have access now, the last day of their direct grant (`ends_on`, a date), and each grant with
# where it comes from. A team grant has no end date, so a person with one keeps access after their direct grant ends.
# %%
response = client.http.post(f'{client.url}/api/v1/projects/{client.project}/access/effective', json={'project_id': client.project},
                            headers=client.credential.headers(client.url, client.project))
members = response.json().get('members', []) if response.status_code == 200 else []
if response.status_code != 200:
    print('Only a project administrator can read who has access:', response.json().get('error') or response.status_code)
for person in members:
    if not person['has_access']:
        state = 'no access' + (f" (ended after {words(date.fromisoformat(person['ends_on']))})" if person['ended'] else '')
    else:
        state = 'until ' + words(date.fromisoformat(person['ends_on'])) if person['ends_on'] else 'no end date'
    through = ', '.join(f"{grant['role_label']} through {grant['source_label']}" for grant in person['grants'])
    print(f"{person['name']}: {state} - {through}")
# %% [markdown]
# ## On one line
# Each person who has access drawn from today to their last day; an arrow means no end date.
# %%
today = datetime.now(timezone.utc).date()
shown = [person for person in members if person['has_access']] or [{'name': row['name'] or row['id'], 'ends_on': row['access_ends_at'] and last_day(row['access_ends_at']).isoformat()} for row in mine]
horizon = max([date.fromisoformat(p['ends_on']) for p in shown if p['ends_on']] + [today + timedelta(days=365)]) + timedelta(days=365)
fig, axis = plt.subplots(figsize=(6, 0.6 * len(shown) + 1))
for line, person in enumerate(shown):
    end = date.fromisoformat(person['ends_on']) if person['ends_on'] else horizon
    axis.plot([today, end], [line, line], linewidth=6, solid_capstyle='butt')
    axis.annotate(words(end) if person['ends_on'] else 'no end date', (end, line), xytext=(10, 0), textcoords='offset points', va='center', fontsize='small')
    if not person['ends_on']: axis.plot([end], [line], marker='>', color='black')
axis.set_yticks(range(len(shown)), [p['name'] for p in shown]); axis.invert_yaxis(); axis.set_xlabel('Last day of access (UTC)')
fig.savefig('who-has-access-until-when.png', bbox_inches='tight'); plt.close(fig)
print('Wrote who-has-access-until-when.png')
