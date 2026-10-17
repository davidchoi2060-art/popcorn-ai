"""게임 카드 자료(api/talk_game_cards) -- 2차 대화 중심 화면의 바닥(2026-10-11).

지어내지 않는다: 없는 칸은 null, 날짜 없는 인기는 안 낸다, 내부 출처 키는 안 나간다,
그림 원천이 없으니 image.state 는 "none", 묶음·내린 게임은 카드로 안 낸다.
"""
import unittest
from unittest.mock import patch

from api import talk_answer as TA
from api import talk_game_cards as GC


def _facts(name, **kw):
    return TA.GameFacts(name=name, **kw)


LOL = _facts('리그 오브 레전드', genre='AOS', vendor='라이엇 게임즈', release_date='2011-12-12', grade='E',
             pcbang_rank=1, pcbang_share=38.5, snapshot_date='2026-09-17', snapshot_source='gametrics',
             copy_spec='  가벼운 사양으로도 잘 돌아가는 팀 대전 게임  ')
PUBG = _facts('배틀그라운드', genre='슈팅', grade='B', steam_ccu=700000, snapshot_date='2026-09-17',
              snapshot_source='steam_api')
BUCKET = _facts('기타 온라인 게임', genre='기타')


class _Conn:
    def __init__(self, hidden=()):
        self.hidden = list(hidden)

    def execute(self, *a, **k):
        rows = [(n,) for n in self.hidden]
        return type('R', (), {'all': lambda s: rows})()


class CardShape(unittest.TestCase):
    def test_full_card(self):
        c = GC.card(LOL)
        self.assertEqual(c['name'], '리그 오브 레전드')
        self.assertEqual(c['release_year'], 2011)
        self.assertEqual(c['summary'], '가벼운 사양으로도 잘 돌아가는 팀 대전 게임')
        self.assertEqual(c['load'], {'grade': 'E', 'word': '보통'})
        self.assertEqual(c['popularity']['kind'], 'pcbang')
        self.assertEqual(c['popularity']['as_of'], '2026-09-17')
        self.assertEqual(c['popularity']['source'], '게임트릭스 PC방 통계')
        self.assertEqual(c['image'], {'state': 'none', 'url': None})

    def test_missing_values_stay_null(self):
        c = GC.card(_facts('무명 게임'))
        for k in ('genre', 'vendor', 'release_year', 'summary', 'load', 'popularity'):
            self.assertIsNone(c[k], k)

    def test_popularity_needs_a_date_and_hides_internal_keys(self):
        self.assertIsNone(GC.popularity(_facts('x', pcbang_rank=3)))
        c = GC.card(PUBG)
        self.assertEqual(c['popularity']['kind'], 'steam')
        self.assertEqual(c['popularity']['ccu'], 700000)
        self.assertNotIn('steam_api', str(c))
        self.assertNotIn('gametrics', str(GC.card(LOL)))

    def test_load_words(self):
        self.assertEqual(GC.card(_facts('a', grade='L'))['load']['word'], '가벼운 편')
        self.assertEqual(GC.card(PUBG)['load']['word'], '무거운 편')
        self.assertIsNone(GC.card(_facts('a', grade='Z'))['load'])


class BuildCards(unittest.TestCase):
    def run_build(self, facts, hidden=(), **kw):
        vocab = object()
        names = {f.name: f for f in facts}
        with patch.object(GC.TS, 'load_vocab', lambda conn: vocab), \
             patch.object(GC.TS, 'match_game', lambda n, v: n if n in names else None), \
             patch.object(GC.TA, 'load_game_facts', lambda conn, ns, v: [names[n] for n in reversed(ns) if n in names]), \
             patch.object(GC.TA, 'popular_games', lambda conn, g, limit: list(facts)):
            return GC.build_cards(_Conn(hidden), **kw)

    def test_names_keep_the_order_the_customer_said(self):
        cards = self.run_build([LOL, PUBG], names=['배틀그라운드', '리그 오브 레전드', '없는 게임'])
        self.assertEqual([c['name'] for c in cards], ['배틀그라운드', '리그 오브 레전드'])

    def test_popular_keeps_rank_order_and_drops_buckets(self):
        cards = self.run_build([LOL, BUCKET, PUBG], hidden=['기타 온라인 게임'], limit=5)
        self.assertEqual([c['name'] for c in cards], ['리그 오브 레전드', '배틀그라운드'])

    def test_limit_is_capped(self):
        many = [_facts('g%d' % i) for i in range(10)]
        self.assertEqual(len(self.run_build(many, limit=99)), GC.MAX_CARDS)


class Route(unittest.TestCase):
    def test_route_registered_under_talk(self):
        paths = [r.path for r in GC.router.routes]
        self.assertIn('/api/talk/game-cards', paths)


if __name__ == '__main__':
    unittest.main()
