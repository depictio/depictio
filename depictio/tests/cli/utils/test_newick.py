"""Newick parsing and pruning shared by ingest and the ampliseq prune script."""

import pytest

from depictio.cli.cli.utils.newick import count_tips, parse_newick, prune, prune_to_tips

TREE = "((a:0.1,b:0.2)ab:0.3,(c:0.4,(d:0.5,e:0.6)de:0.7)cde:0.8)root;"


def _tips(newick: str) -> set[str]:
    tree, _ = parse_newick(newick)
    return set(tree.tips())


class TestParse:
    def test_tips_labels_and_lengths(self):
        tree, root = parse_newick(TREE)

        assert count_tips(tree) == 5
        assert tree.name[root] == "root"
        assert tree.length[tree.name.index("a")] == pytest.approx(0.1)
        assert tree.length[tree.name.index("cde")] == pytest.approx(0.8)

    def test_comments_and_quotes_are_not_labels(self):
        tree, _ = parse_newick("('a':0.1[&support=90],b:0.2[note]);")

        assert sorted(tree.tips()) == ["a", "b"]
        assert sorted(tree.length[i] for i, k in enumerate(tree.children) if not k) == [0.1, 0.2]

    def test_a_deep_ladder_does_not_overflow(self):
        """A recursive walk dies on a ladderised tree long before memory does."""
        depth = 20_000
        newick = "(" * depth + "t0" + "".join(f",t{i + 1})" for i in range(depth)) + ";"

        tree, root = parse_newick(newick)
        assert count_tips(tree) == depth + 1
        assert _tips(prune(tree, root, {"t0", f"t{depth}"})) == {"t0", f"t{depth}"}


class TestPrune:
    def test_keeps_only_the_wanted_tips(self):
        tree, root = parse_newick(TREE)

        assert _tips(prune(tree, root, {"a", "d", "e"})) == {"a", "d", "e"}

    def test_single_child_nodes_fold_into_their_child(self):
        """Dropping b leaves ab with one child: a takes ab's branch (0.1 + 0.3)."""
        tree, root = parse_newick(TREE)

        out = prune(tree, root, {"a", "c"})

        assert out == "(a:0.4,c:1.2)root;"

    def test_key_maps_labels_before_matching(self):
        tree, root = parse_newick("(ASV1_Bacteria:1,ASV2_Archaea:1,ASV3_x:1);")

        out = prune(tree, root, {"ASV1", "ASV3"}, key=lambda n: n.split("_")[0])

        assert _tips(out) == {"ASV1_Bacteria", "ASV3_x"}

    def test_no_wanted_tip_is_an_error(self):
        tree, root = parse_newick(TREE)

        with pytest.raises(ValueError):
            prune(tree, root, {"zzz"})


class TestPruneToTips:
    def test_a_tree_at_the_threshold_comes_back_byte_for_byte(self):
        result = prune_to_tips(TREE, {"a"}, max_tips=5)

        assert result.newick == TREE
        assert not result.pruned
        assert (result.tips_before, result.tips_after) == (5, 5)

    def test_a_tree_over_the_threshold_is_pruned(self):
        result = prune_to_tips(TREE, {"a", "b", "c"}, max_tips=3)

        assert result.pruned
        assert (result.tips_before, result.tips_after) == (5, 3)
        assert _tips(result.newick) == {"a", "b", "c"}
        assert result.newick.endswith(";\n")

    def test_wanted_ids_absent_from_the_tree_are_ignored(self):
        result = prune_to_tips(TREE, {"a", "b", "not-in-tree"}, max_tips=2)

        assert _tips(result.newick) == {"a", "b"}
