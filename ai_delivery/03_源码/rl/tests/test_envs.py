"""test_envs.py —— 环境单元测试（纯标准库 + unittest + numpy，不依赖 torch / gymnasium）

★ 必须能在没有 torch / gymnasium 的机器上全部通过。
运行（在 ai_training 目录）：
    python -m unittest discover -s src/rl/tests -t .
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

# 让测试能 import 到 src/rl（与运行方式无关）
_RL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RL_DIR not in sys.path:
    sys.path.insert(0, _RL_DIR)

from scope_env import (ScopeEnv, OBS_DIM, WAVE_SINE, WAVE_NAMES,       # noqa: E402
                       occupy_reward, centering_reward, cycles_reward,
                       is_triggered, compute_scope_reward,
                       make_gymnasium_scope_env)
from audio_eq_env import (AudioEqEnv, OBS_DIM_EQ, DEFAULT_ROOM,        # noqa: E402
                          flatness_metric, eq_reward, rms_db_error,
                          room_response_db, eq_response_db,
                          third_octave_smooth, make_gymnasium_eq_env)


class TestScopeEnvInterface(unittest.TestCase):
    def test_reset_obs_shape_and_dtype(self):
        env = ScopeEnv(seed=0)
        obs = env.reset()
        self.assertEqual(obs.shape, (OBS_DIM,))
        self.assertEqual(obs.dtype, np.float32)
        self.assertTrue(np.all(obs >= -1.0 - 1e-6) and np.all(obs <= 1.0 + 1e-6))

    def test_step_returns_4tuple(self):
        env = ScopeEnv(seed=1)
        env.reset()
        out = env.step((8, 8, 2))
        self.assertEqual(len(out), 4)
        obs, reward, done, info = out
        self.assertEqual(obs.shape, (OBS_DIM,))
        self.assertIsInstance(reward, float)
        self.assertIsInstance(done, (bool, np.bool_))
        self.assertIn("t_occupy", info)
        self.assertIn("t_center", info)
        self.assertIn("t_cycles", info)
        self.assertIn("lost", info)

    def test_step_rejects_bad_action(self):
        env = ScopeEnv(seed=1)
        env.reset()
        with self.assertRaises(ValueError):
            env.step((1, 2))  # 长度不对

    def test_render_text(self):
        env = ScopeEnv(seed=2)
        env.reset()
        s = env.render_text()
        self.assertIsInstance(s, str)
        self.assertTrue(len(s) > 0)
        self.assertIn("回报分解", s)


class TestScopeRewardFormula(unittest.TestCase):
    def test_occupy_reward(self):
        self.assertAlmostEqual(occupy_reward(0.7), 1.0)          # 目标区间内
        self.assertAlmostEqual(occupy_reward(0.5), 0.5)          # 下坡中点
        self.assertAlmostEqual(occupy_reward(0.3), 0.0)          # 太低
        self.assertAlmostEqual(occupy_reward(0.9), 0.5)          # 上坡中点
        self.assertAlmostEqual(occupy_reward(1.1), 0.0)          # 太高

    def test_centering_reward(self):
        self.assertAlmostEqual(centering_reward(100.0, 100.0, 100.0), 1.0)
        self.assertAlmostEqual(centering_reward(100.0, 150.0, 100.0), 0.0)  # 边缘
        self.assertAlmostEqual(centering_reward(125.0, 100.0, 100.0), 0.5)
        self.assertEqual(centering_reward(100.0, 100.0, 0.0), 0.0)  # 平线

    def test_cycles_reward(self):
        self.assertAlmostEqual(cycles_reward(3.0), 1.0)
        self.assertAlmostEqual(cycles_reward(2.0), 1.0)
        self.assertAlmostEqual(cycles_reward(5.0), 1.0)
        self.assertAlmostEqual(cycles_reward(1.25), 0.5)
        self.assertAlmostEqual(cycles_reward(0.4), 0.0)
        self.assertAlmostEqual(cycles_reward(6.0), 1.0 / 3.0, places=5)

    def test_is_triggered(self):
        self.assertTrue(is_triggered(100.0, 50.0, 150.0))
        self.assertTrue(is_triggered(50.0, 50.0, 150.0))   # 边界含
        self.assertFalse(is_triggered(200.0, 50.0, 150.0))

    def test_reward_decomposition_sums(self):
        # 构造一个已知信号，验证 reward = w1*t1 + w2*t2 + w3*t3 - w4*lost
        n = 4096
        ph = np.arange(n) * (3.0 / n)                       # 3 个周期
        samples = np.clip(np.rint(127.5 + 80.0 * np.sin(2 * np.pi * ph)), 0, 255).astype(np.uint8)
        w = (1.0, 0.6, 1.0, 0.8)
        r = compute_scope_reward(samples, trig=128, dec=15, wave_kind=WAVE_SINE,
                                 f_hz=1000.0, weights=w)
        self.assertAlmostEqual(r["reward"],
                               w[0] * r["t_occupy"] + w[1] * r["t_center"]
                               + w[2] * r["t_cycles"] - w[3] * r["lost"], places=6)
        self.assertAlmostEqual(r["t_cycles"], 1.0)          # K=3.07 在 [2,5]
        self.assertTrue(r["triggered"])


class TestScopeTermination(unittest.TestCase):
    def test_episode_ends_within_max_steps(self):
        env = ScopeEnv(seed=7, max_steps=3)
        env.reset()
        done = False
        for _ in range(3):
            _, _, done, info = env.step((4, 6, 3))
            if done:
                break
        self.assertTrue(done)
        self.assertTrue(info["terminated"] or info["truncated"])

    def test_success_terminates_early(self):
        # 构造干净的已知信号，选对 (trig=136, dec=15, vgain=1.0) 应成功
        env = ScopeEnv(seed=0, fixed_wave=WAVE_SINE, max_steps=10)
        env.reset()
        env.wave_kind = WAVE_SINE
        env.f_hz = 1000.0
        env.amp = 80.0
        env.dc = 0.0
        env.phase0 = 0.0
        env.noise = 0.0
        _, _, done, info = env.step((8, 7, 2))   # trig=136, DEC=15, vgain=1.0
        self.assertTrue(info["success"])
        self.assertTrue(info["terminated"])
        self.assertTrue(done)


class TestScopeSeedReproducibility(unittest.TestCase):
    def test_same_seed_same_trajectory(self):
        e1 = ScopeEnv(seed=42)
        e2 = ScopeEnv(seed=42)
        o1 = e1.reset()
        o2 = e2.reset()
        np.testing.assert_array_equal(o1, o2)
        a = (3, 5, 1)
        r1 = e1.step(a)
        r2 = e2.step(a)
        np.testing.assert_array_equal(r1[0], r2[0])
        self.assertEqual(r1[1], r2[1])
        self.assertEqual(bool(r1[2]), bool(r2[2]))

    def test_different_seed_different_capture(self):
        e1 = ScopeEnv(seed=42)
        e3 = ScopeEnv(seed=43)
        e1.reset()
        e3.reset()
        self.assertFalse(np.array_equal(e1._last_samples, e3._last_samples))

    def test_reset_with_seed(self):
        e1 = ScopeEnv(seed=42)
        e2 = ScopeEnv(seed=42)
        o1 = e1.reset(seed=99)
        o2 = e2.reset(seed=99)
        np.testing.assert_array_equal(o1, o2)


class TestAudioEqEnvInterface(unittest.TestCase):
    def test_reset_obs_shape_and_dtype(self):
        env = AudioEqEnv(seed=0)
        obs = env.reset()
        self.assertEqual(obs.shape, (OBS_DIM_EQ,))
        self.assertEqual(obs.dtype, np.float32)

    def test_step_returns_4tuple(self):
        env = AudioEqEnv(seed=1)
        env.reset()
        out = env.step((4, 4, 4, 4, 4, 4, 4, 4))   # 全 0 dB
        self.assertEqual(len(out), 4)
        obs, reward, done, info = out
        self.assertEqual(obs.shape, (OBS_DIM_EQ,))
        self.assertIn("flatness", info)
        self.assertIn("rms_err", info)
        self.assertIn("gains_db", info)

    def test_render_text(self):
        env = AudioEqEnv(seed=2)
        env.reset()
        s = env.render_text()
        self.assertIsInstance(s, str)
        self.assertIn("RMS误差", s)


class TestAudioEqRewardFormula(unittest.TestCase):
    def test_flatness_metric(self):
        flat0 = np.zeros(8)
        self.assertAlmostEqual(flatness_metric(flat0), 0.0)
        resp = np.zeros(8)
        resp[0] = 20.0
        self.assertAlmostEqual(flatness_metric(resp), -1.0 / 8.0, places=6)

    def test_rms_db_error(self):
        self.assertAlmostEqual(rms_db_error(np.array([3.0, 4.0])),
                               np.sqrt((9.0 + 16.0) / 2.0), places=6)

    def test_eq_reward_flat_and_penalty(self):
        resp = np.zeros(8)
        gains = np.zeros(8)
        self.assertAlmostEqual(eq_reward(resp, gains, w_gain=0.02), 0.0)
        gains_pen = np.full(8, 12.0)
        expected = 0.0 - 0.02 * 1.0   # (12/12)^2 = 1
        self.assertAlmostEqual(eq_reward(resp, gains_pen, w_gain=0.02), expected, places=6)

    def test_room_has_low_and_high_rolloff(self):
        resp = room_response_db(np.array([125.0, 1000.0, 16000.0]), DEFAULT_ROOM)
        self.assertLess(resp[0], -5.0)    # 低频塌陷
        self.assertLess(resp[2], -5.0)    # 高频衰减

    def test_eq_can_flatten_room(self):
        # 初始不平坦，理想 EQ 补偿后明显更平（验证"明显改善"前提成立）
        centers = np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0])
        grid = _grid()
        room = room_response_db(grid, DEFAULT_ROOM)
        resp0 = third_octave_smooth(grid, room, centers)
        self.assertGreater(rms_db_error(resp0), 3.0)
        gains = -resp0   # 理想补偿（连续，未量化）
        total = room + eq_response_db(grid, gains)
        resp1 = third_octave_smooth(grid, total, centers)
        self.assertLess(rms_db_error(resp1), rms_db_error(resp0))


def _grid():
    return np.geomspace(20.0, 20000.0, 129)


class TestAudioEqTerminationAndSeed(unittest.TestCase):
    def test_episode_ends_within_max_steps(self):
        env = AudioEqEnv(seed=7, max_steps=3)
        env.reset()
        done = False
        for _ in range(3):
            _, _, done, info = env.step((4, 4, 4, 4, 4, 4, 4, 4))
            if done:
                break
        self.assertTrue(done)

    def test_same_seed_same_trajectory(self):
        e1 = AudioEqEnv(seed=42)
        e2 = AudioEqEnv(seed=42)
        o1 = e1.reset()
        o2 = e2.reset()
        np.testing.assert_array_equal(o1, o2)
        a = (6, 5, 4, 3, 4, 5, 6, 7)
        r1 = e1.step(a)
        r2 = e2.step(a)
        np.testing.assert_array_equal(r1[0], r2[0])
        self.assertEqual(r1[1], r2[1])


class TestGymnasiumWrapperOptional(unittest.TestCase):
    def test_scope_wrapper(self):
        g = make_gymnasium_scope_env()
        if g is None:
            self.skipTest("gymnasium 未安装，跳过包装测试")
        env = g()
        obs, info = env.reset(seed=0)
        self.assertEqual(obs.shape, (OBS_DIM,))
        obs, reward, terminated, truncated, info = env.step((8, 8, 2))
        self.assertEqual(obs.shape, (OBS_DIM,))
        self.assertIsInstance(reward, float)

    def test_eq_wrapper(self):
        g = make_gymnasium_eq_env()
        if g is None:
            self.skipTest("gymnasium 未安装，跳过包装测试")
        env = g()
        obs, info = env.reset(seed=0)
        self.assertEqual(obs.shape, (OBS_DIM_EQ,))
        obs, reward, terminated, truncated, info = env.step((4, 4, 4, 4, 4, 4, 4, 4))
        self.assertEqual(obs.shape, (OBS_DIM_EQ,))


if __name__ == "__main__":
    unittest.main()
