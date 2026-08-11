#!/usr/bin/env python3
"""Install all git deps from hmm.json via GitHub tarball + haxelib dev.

Reason: haxelib git uses a shallow clone (--depth 1) which can only
checkout the repo HEAD. hmm.json pins specific commits that are NOT
HEAD for some repos (hxcpp, lime, ...), so `haxelib git` fails with
"Could not checkout branch, tag or path".

Tarball download works for ANY commit SHA and avoids git protocol.
This script:
1. Reads hmm.json
2. Removes all git deps from it (so hmm only installs haxelib deps)
3. Downloads each git dep tarball, extracts, and `haxelib dev`s it
"""
import json, os, subprocess, urllib.request, tarfile, shutil, sys

MODE = sys.argv[1] if len(sys.argv) > 1 else 'all'
BASE = '/tmp/haxelib-deps'
os.makedirs(BASE, exist_ok=True)

with open('hmm.json') as f:
    data = json.load(f)

deps = data['dependencies']
git_deps = [d for d in deps if d.get('type') == 'git']

def download(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': 'WorkBuddy-CI'})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)

def extract(tgz, target):
    with tarfile.open(tgz, 'r:gz') as t:
        for m in t.getmembers():
            parts = m.name.split('/', 1)
            m.name = parts[1] if len(parts) == 2 else parts[0]
        t.extractall(target, filter='data')

def fetch_all():
    for dep in git_deps:
        name = dep['name']
        target = os.path.join(BASE, name)
        if os.path.isdir(target) and os.listdir(target):
            print(f'== {name}: already present, skip', flush=True)
            continue
        ref = dep['ref']
        url = dep['url'].rstrip('/').removesuffix('.git')
        if not url.startswith('http'):
            url = 'https://github.com/' + url
        repo_path = url.replace('https://github.com/', '').replace('http://github.com/', '')
        tgz = os.path.join(BASE, name + '.tar.gz')
        dl_url = f'https://codeload.github.com/{repo_path}/tar.gz/{ref}'
        print(f'== {name}: downloading {dl_url}', flush=True)
        try:
            download(dl_url, tgz)
        except Exception as e:
            print(f'!! {name}: download failed: {e}', file=sys.stderr)
            sys.exit(1)
        os.makedirs(target, exist_ok=True)
        extract(tgz, target)
    print('All tarballs downloaded and extracted')

def dev_all():
    # hmm install uses '--never' (local repo .haxelib). Our dev links MUST
    # target the same repo or the override is silently ignored (lime 8.3.2 wins).
    subprocess.run(['haxelib', '--never', 'newrepo', '--quiet'], check=True)
    for dep in git_deps:
        name = dep['name']
        target = os.path.join(BASE, name)
        dev_path = target
        if dep.get('dir'):
            dev_path = os.path.join(target, dep['dir'])
        print(f'== {name}: haxelib --never dev -> {dev_path}', flush=True)
        subprocess.run(['haxelib', '--never', 'dev', name, dev_path], check=True)
    print('All git deps dev-linked (local repo .haxelib)')

if MODE == 'prepare':
    # Strip git deps so `hmm install` only handles haxelib deps,
    # then download + extract tarballs (no dev links yet)
    data['dependencies'] = [d for d in deps if d.get('type') != 'git']
    with open('hmm.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Removed {len(git_deps)} git deps from hmm.json, kept {len(data["dependencies"])} haxelib deps')
    fetch_all()
elif MODE == 'dev':
    # Cache may have hit (tarballs in /tmp wiped), so fetch first (skips existing)
    fetch_all()
    dev_all()
else:
    # all: prepare + dev (legacy / local runs)
    data['dependencies'] = [d for d in deps if d.get('type') != 'git']
    with open('hmm.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f'Removed {len(git_deps)} git deps from hmm.json, kept {len(data["dependencies"])} haxelib deps')
    fetch_all()
    dev_all()
