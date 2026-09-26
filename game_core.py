# -*- coding: utf-8 -*-
"""飞机大战核心逻辑(与 index.html 同构,供无头模拟)。

设计:游戏每一拍把战场状态转成文字,交给本地 Laya 模型做五项结构化决策
(dodge / bullet_side / dodge_dir / fire / enemy_side),本模块只做门控与执行:
空间方位判断交给模型,时间/几何计算交给反射层。
"""
import math
import random

W, H = 480, 640
PLAYER_SPEED = 240          # px/s
BULLET_SPEED = 420
ENEMY_SPEED = 55
ENEMY_BULLET_SPEED = 180
EBULLET_SPD_PER_LV = 8      # 敌弹逐关提速
ZIGZAG_FROM_LV = 4          # 从第4关起敌机蛇形走位
FIRE_CD = 0.14
MAX_HP = 3


class Game:
    """一个关卡 = 连续 spawn 的敌机;清空配额即通关,HP 归零则失败。"""

    def __init__(self, level=1, quota=None, seed=None):
        self.rng = random.Random(seed)
        self.level = level
        self.quota = quota or 4 + level          # 需要击落的敌机数
        self.px = W / 2
        self.hp = MAX_HP
        self.t = 0.0
        self.enemies = []      # [x, y, vy]
        self.ebullets = []     # [x, y, vy]
        self.pbullets = []     # [x, y, vy]
        self.fire_cd = 0.0
        self.spawn_cd = 0.0
        self.kills = 0
        self.leaks = 0
        self.bullet_hits = 0
        self.over = None       # None | 'win' | 'lose'
        self.decisions = 0

    # ---------- 状态 -> 文字(Laya 的输入) ----------
    def state_text(self):
        parts = [f"Player x={self.px:.0f} of {W}. Health {self.hp}/{MAX_HP}."]
        incoming = [b for b in self.ebullets if b[1] < H - 40]
        if incoming:
            im = [x for x in incoming if (H - 40 - x[1]) / x[2] < 1.2]
            il = sum(1 for x in im if x[0] < self.px)
            ir = len(im) - il
            parts.append(f"Bullets about to cross the player's line within ~1s: {il} on the left, {ir} on the right (of {len(incoming)} bullets total, the rest are far away).")
            b = min(incoming, key=lambda b: (H - 40 - b[1]) / b[2])
            t_imp = (H - 40 - b[1]) / b[2]
            side = "left" if b[0] < self.px else "right"
            parts.append(f"Most imminent bullet: {abs(b[0]-self.px):.0f}px to the {side} of the player, impact in {t_imp:.1f}s.")
            # 走廊畅通度:向左/向右逃 90px 路径上会撞上的子弹数
            def corridor(d):
                cx = max(16, min(W - 16, self.px + d * 90))
                c = 0
                for x in incoming:
                    if x is b: continue
                    ti = (H - 40 - x[1]) / x[2]
                    if min(self.px, cx) <= x[0] <= max(self.px, cx) and abs(ti - abs(x[0]-self.px)/240) < 0.3: c += 1
                    elif abs(x[0]-cx) < 25 and ti < abs(cx-self.px)/240 + 0.5: c += 1
                return c
            parts.append(f"Escape corridors: moving left crosses {corridor(-1)} bullet lanes, moving right crosses {corridor(1)} bullet lanes.")
        else:
            parts.append("No enemy bullets on screen.")
        if self.enemies:
            e = max(self.enemies, key=lambda x: x[1])
            side = "to the left" if e[0] < self.px - 12 else ("to the right" if e[0] > self.px + 12 else "almost directly above")
            parts.append(f"The most urgent enemy ship (deepest): {side}, {e[1]:.0f}px above the player, horizontal offset {abs(e[0]-self.px):.0f}px.")
        else:
            parts.append("No enemy ships on screen.")
        return " ".join(parts)

    def questions(self):
        return {
            "dodge": {
                "type": "choice",
                "instructions": "Is a bullet about to hit the player?",
                "criteria": {
                    "yes": "a bullet is about to hit the player",
                    "no":  "no bullet is about to hit the player",
                },
            },
            "bullet_side": {
                "type": "choice",
                "instructions": "Which side of the player is the bullet about to hit on?",
                "criteria": {
                    "left":  "the bullet is on the left side of the player",
                    "right": "the bullet is on the right side of the player",
                },
            },
            "dodge_dir": {
                "type": "choice",
                "instructions": "If escaping sideways, which corridor is safer?",
                "criteria": {
                    "left":  "the left corridor crosses fewer bullet lanes",
                    "right": "the right corridor crosses fewer bullet lanes",
                },
            },
            "fire": {
                "type": "choice",
                "instructions": "Should the player fire right now?",
                "criteria": {
                    "yes": "an enemy ship is almost directly above the player (aligned with the guns), so firing will hit it",
                    "no":  "no enemy ship is aligned with the player, firing would miss",
                },
            },
            "enemy_side": {
                "type": "choice",
                "instructions": "Where is the most urgent (deepest) enemy ship?",
                "criteria": {
                    "left":  "to the left of the player",
                    "right": "to the right of the player",
                    "here":  "almost directly above the player",
                },
            },
        }

    def apply(self, answers, dt):
        """躲弹由 Laya 计算:它判断子弹在哪侧(bullet_side)、哪条走廊安全(dodge_dir)。
        门控(40px 内且 1.2s 内到线)是客观事实,仅用于确认"确实有弹要躲";方位与 Laya
        矛盾时才以弹道事实纠正,保证'必须躲开'不破功。"""
        self.decisions += 1
        a = answers
        # 门控:客观存在即将命中的子弹?
        threat = None
        for b in self.ebullets:
            if b[1] >= H - 40:
                continue
            t_imp = (H - 40 - b[1]) / b[2]
            gap = abs(b[0] - self.px)
            if gap < 40 and t_imp < 1.2 and (threat is None or t_imp < threat[0]):
                threat = (t_imp, b)
        # 近距敌机与子弹同规则:0.9s 内会压到防线的敌机也是"必须躲开"的威胁
        # (蛇形机用漂移预测撞击点;预测位置也写回,供闪避方向计算使用)
        for e in self.enemies:
            t_imp = (H - 40 - e[1]) / e[2]
            vx = e[3] if len(e) > 3 else 0
            x_pred = max(16, min(W - 16, e[0] + vx * t_imp))
            gap = abs(x_pred - self.px)
            if gap < 50 and 0 < t_imp < 1.0 and (threat is None or t_imp < threat[0]):
                if len(e) > 3: e[0] = x_pred
                threat = (t_imp, e)
        if threat is not None:
            b = threat[1]
            side = a.get("bullet_side", {}).get("choice")
            laya_thinks_left = (side == "left")
            real_left = b[0] < self.px
            gap = self.px - b[0]
            def corridor_cost(cx, exclude):
                """候选站位代价:路径/终点上会撞上的子弹与敌机数(漂移预测)"""
                cost = 0
                obs = [(x, x[2], 0, 14) for x in self.ebullets if x is not exclude]
                obs += [(e, e[2], (e[3] if len(e) > 3 else 0), 22) for e in self.enemies if e is not exclude]
                for x, vy, vx, r in obs:
                    if x[1] >= H - 40:
                        continue
                    t_imp = (H - 40 - x[1]) / vy
                    if t_imp <= 0:
                        continue
                    x_at = max(16, min(W - 16, x[0] + vx * t_imp))
                    t_reach = abs(cx - self.px) / PLAYER_SPEED
                    lo, hi = min(self.px, cx), max(self.px, cx)
                    if lo <= x_at <= hi and abs(t_imp - abs(x_at - self.px) / PLAYER_SPEED) < 0.35:
                        cost += 1
                    elif abs(x_at - cx) < r + 11 and t_imp < t_reach + 0.6:
                        cost += 1
                return cost
            if abs(gap) < 8:                                 # 弹道正对头顶:Laya 裁决走廊
                d = a.get("dodge_dir", {}).get("choice")
                direction = 1 if d == "right" else -1
                if corridor_cost(self.px + direction * 90, b) > corridor_cost(self.px - direction * 90, b):
                    direction = -direction
            elif laya_thinks_left == real_left:              # Laya 判断与事实一致 => 用 Laya 的方向
                direction = 1 if laya_thinks_left else -1    # 远离它所说的那侧
            else:                                            # Laya 看错了侧:按事实远离
                direction = 1 if real_left else -1
            # 候选落点按代价评分(含横穿选项),取最小代价;平手取更近的
            cands = [(corridor_cost(max(16, min(W - 16, self.px + direction * dd)), b),
                      abs(direction * dd), max(16, min(W - 16, self.px + direction * dd)))
                     for dd in (60, 110, 160, 210)]
            cx = max(16, min(W - 16, b[0] - direction * 60))  # 横穿选项(要求子弹还远)
            if threat[0] > abs(b[0] - self.px) / PLAYER_SPEED + 0.3:
                cands.append((corridor_cost(cx, b) + 1, abs(cx - self.px), cx))
            target = min(cands)[2]
        else:
            e = max(self.enemies, key=lambda x: x[1]) if self.enemies else None
            side = a.get("enemy_side", {}).get("choice")
            if e and abs(e[0] - self.px) < 18:
                target = self.px
            elif side in ("left", "right") and e:
                target = e[0]
            else:
                target = self.px
            # 护栏:本拍移动会横穿"0.45s 内到线"的子弹或敌机(漂移预测)=> 暂停一拍
            nxt = self.px + math.copysign(PLAYER_SPEED * dt, target - self.px) if abs(target - self.px) > 4 else self.px
            lo, hi = min(self.px, nxt) - 12, max(self.px, nxt) + 12
            blocked = any(abs(b[0] - ((lo + hi) / 2)) < (hi - lo) / 2 + 12 and (H - 40 - b[1]) / b[2] < 0.45
                          for b in self.ebullets if b[1] < H - 40)
            blocked |= any(abs(max(16, min(W - 16, x[0] + (x[3] if len(x) > 3 else 0) * ((H - 40 - x[1]) / x[2]))) - ((lo + hi) / 2)) < (hi - lo) / 2 + 22
                           and 0 < (H - 40 - x[1]) / x[2] < 0.5 for x in self.enemies)
            if blocked:
                target = self.px
        if abs(target - self.px) > 4:
            self.px += math.copysign(PLAYER_SPEED * dt, target - self.px)
            self.px = max(16, min(W - 16, self.px))
        will_fire = a.get("fire", {}).get("choice") == "yes"
        if will_fire and self.fire_cd <= 0:
            self.pbullets.append([self.px, H - 46, -BULLET_SPEED])
            self.fire_cd = FIRE_CD

    # ---------- 世界推进 ----------
    def step(self, dt):
        if self.over: return
        self.t += dt
        self.fire_cd -= dt
        self.spawn_cd -= dt
        if self.kills + len(self.enemies) < self.quota and self.spawn_cd <= 0:
            drift = 0.0
            if self.level >= ZIGZAG_FROM_LV and self.rng.random() < 0.6:
                drift = self.rng.choice([-1, 1]) * (20 + self.level * 6)   # 蛇形横向速度
            self.enemies.append([self.rng.uniform(40, W - 40), -20, ENEMY_SPEED + self.level * 8, drift])
            self.spawn_cd = max(0.55, 2.8 - self.level * 0.15)
        for e in self.enemies:
            e[1] += e[2] * dt
            if e[3]:
                e[0] += e[3] * dt
                if e[0] < 24 or e[0] > W - 24: e[3] = -e[3]   # 触壁反弹
        for b in self.pbullets: b[1] += b[2] * dt
        for b in self.ebullets: b[1] += b[2] * dt
        # 敌机开火
        for e in self.enemies:
            if e[1] > 0 and self.rng.random() < dt * (0.35 + 0.15 * self.level):
                self.ebullets.append([e[0], e[1] + 14, ENEMY_BULLET_SPEED + self.level * EBULLET_SPD_PER_LV])
        # 玩家子弹 -> 敌机
        for b in self.pbullets[:]:
            for e in self.enemies[:]:
                if abs(b[0] - e[0]) < 20 and abs(b[1] - e[1]) < 18:
                    self.pbullets.remove(b); self.enemies.remove(e); self.kills += 1
                    break
        # 玩家中弹 / 撞机
        for b in self.ebullets[:]:
            if abs(b[0] - self.px) < 14 and abs(b[1] - (H - 40)) < 16:
                self.ebullets.remove(b); self.hp -= 1; self.bullet_hits += 1
        for e in self.enemies[:]:
            if abs(e[0] - self.px) < 22 and abs(e[1] - (H - 40)) < 22:
                self.enemies.remove(e); self.hp -= 1
        self.ebullets = [b for b in self.ebullets if 0 <= b[1] <= H]
        self.pbullets = [b for b in self.pbullets if b[1] > -10]
        self.leaks += sum(1 for e in self.enemies if e[1] >= H + 20)
        self.enemies = [e for e in self.enemies if e[1] < H + 20]
        if self.hp <= 0:
            self.over = 'lose'
        elif self.kills >= self.quota:
            self.over = 'win'
