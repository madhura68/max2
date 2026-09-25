import unittest

from backup_excludes import is_excluded


class BackupExcludesTest(unittest.TestCase):
    def test_no_patterns(self):
        self.assertFalse(is_excluded("/srv/a.txt", []))

    def test_anchored_file(self):
        self.assertTrue(is_excluded("/srv/app/.env", ["/srv/app/.env"]))
        self.assertFalse(is_excluded("/x/srv/app/.env", ["/srv/app/.env"]))

    def test_unanchored_matches_any_depth(self):
        self.assertTrue(is_excluded("/srv/a/b/cache.tmp", ["*.tmp"]))
        self.assertTrue(is_excluded("/srv/a/data/x.bin", ["data/*.bin"]))
        self.assertFalse(is_excluded("/srv/a/mydata/x.bin", ["data/*.bin"]))

    def test_star_does_not_cross_slash(self):
        self.assertFalse(is_excluded("/srv/a/b.log", ["/srv/*.log"]))
        self.assertTrue(is_excluded("/srv/b.log", ["/srv/*.log"]))

    def test_question_mark(self):
        self.assertTrue(is_excluded("/srv/w1.log", ["/srv/w?.log"]))
        self.assertFalse(is_excluded("/srv/w10.log", ["/srv/w?.log"]))

    def test_directory_excludes_everything_below(self):
        self.assertTrue(is_excluded("/srv/media/pg/base/1/2", ["/srv/media/pg"]))

    def test_dir_only_pattern(self):
        self.assertTrue(is_excluded("/srv/x/node_modules/a/index.js", ["node_modules/"]))
        self.assertFalse(is_excluded("/srv/x/node_modules", ["node_modules/"]))

    def test_double_star(self):
        pats = ["/srv/**/pgdata"]
        self.assertTrue(is_excluded("/srv/pgdata/PG_VERSION", pats))
        self.assertTrue(is_excluded("/srv/a/b/pgdata/base/1", pats))
        self.assertFalse(is_excluded("/srv/a/b/pgdatax/base", pats))
        self.assertFalse(is_excluded("/var/pgdata/x", pats))

    def test_last_match_wins_and_negation(self):
        pats = ["*.log", "!keep.log"]
        self.assertTrue(is_excluded("/srv/a/drop.log", pats))
        self.assertFalse(is_excluded("/srv/a/keep.log", pats))
        self.assertTrue(is_excluded("/srv/a/keep.log", pats + ["/srv/a/*"]))

    def test_negation_cannot_rescue_file_in_excluded_dir(self):
        pats = ["/srv/data/", "!/srv/data/keep.txt"]
        self.assertTrue(is_excluded("/srv/data/keep.txt", pats))

    def test_negation_can_reinclude_directory(self):
        pats = ["/srv/*/", "!/srv/apps/"]
        self.assertTrue(is_excluded("/srv/media/a.jpg", pats))
        self.assertFalse(is_excluded("/srv/apps/a.yml", pats))

    def test_comments_and_blanks_ignored(self):
        self.assertFalse(is_excluded("/srv/#x", ["# /srv/#x", ""]))
        self.assertFalse(is_excluded("/srv/a", ["#a", "#/srv/a", ""]))

    def test_regex_special_chars_are_literal(self):
        self.assertTrue(is_excluded("/srv/a+b(1).[x]", ["/srv/a+b(1).[x]"]))
        self.assertFalse(is_excluded("/srv/aab(1).[x]", ["/srv/a+b(1).[x]"]))
        self.assertFalse(is_excluded("/srv/fooxlog", ["/srv/foo.log"]))


if __name__ == "__main__":
    unittest.main()
