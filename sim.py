# -*- coding: utf-8 -*-
"""无头模拟:Laya 决策控制器能不能通关。用法: python sim.py [关卡] [局数]"""
import sys, time
from laya import Router
from game_core import Game, MAX_HP

router = Router()
DECIDE_EVERY = 0.15          # 决策间隔(秒)

def play(level, verbose=False):
    g = Game(level=level, seed=level * 100 + int(time.time()) % 1000)
    last_ask = -1
    answers = {}
    while not g.over and g.t < 90:
        if g.t - last_ask >= DECIDE_EVERY:
            r = router.predict(g.state_text(), g.questions(), model="multilingual")
            answers = r["answers"]
            last_ask = g.t
        g.apply(answers, 0.016)
        g.step(0.016)
    return g

if __name__ == "__main__":
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    wins = 0
    for i in range(runs):
        t0 = time.time()
        g = play(level)
        wins += g.over == 'win'
        print(f"L{level} 第{i+1}局: {g.over}  击落 {g.kills}/{g.quota}  漏敌 {g.leaks}  中弹 {g.bullet_hits}  HP {g.hp}/{MAX_HP}  "
              f"决策 {g.decisions} 次  用时 {time.time()-t0:.0f}s")
    print(f"\n通关率: {wins}/{runs}")
