#!/usr/bin/env python3
#encoding=utf-8

import os, os.path
from subprocess import run, PIPE
import time

EXT_WHITE = ['.md'] #, '.doc', '.docx', '.pdf', '.xls', '.xlsx', '.txt', '.ppt', '.pptx')

def collect_files(parentDir) :
    children = os.listdir(parentDir)
    children.sort()
    for name in children :
        if name.startswith('.') :
            continue

        path = os.path.join(parentDir, name)
        if os.path.isdir(path) :
            if not name.endswith('.assets') and name not in ['tools'] :
                for i in collect_files(path) :
                    yield i
            continue

        ext = os.path.splitext(name)[1]
        if ext in EXT_WHITE :
            if name.lower() == 'readme.md' :
                continue
            yield path

if __name__ == '__main__' :
    rootDir = run('git rev-parse --show-toplevel'.split(' '), stdout = PIPE).stdout.decode('utf8').rstrip()
    print("rootDir = {}".format(rootDir))

    toc = ''
    for file in collect_files(rootDir) :
        relpath = os.path.relpath(file, rootDir)
        base_name = os.path.splitext(os.path.basename(file))[0]

        mtime = os.path.getmtime(file)
        localtime = time.localtime(mtime)
        mtime_text = time.strftime('%Y-%m-%d %H:%M', localtime)
        print(os.path.relpath(file, rootDir), '最后更新:', mtime_text)

        toc += '- [{}]({}) (最近更新：{})\n'.format(base_name, relpath, mtime_text)

    with open('tools/README-template.md', 'rt', encoding = 'utf-8') as f :
        template = f.read()

    content = template.replace('[TOC]', toc)
    with open('README.md', 'wt', encoding = 'utf-8') as f :
        f.write(content)
