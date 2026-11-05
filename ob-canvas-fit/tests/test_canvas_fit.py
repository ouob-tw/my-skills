"""Run: cd ob-canvas-fit/tests && uv run --no-project python test_canvas_fit.py"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import canvas_fit as cf

RAW = (
    '{\n\t"nodes":[\n'
    '\t\t{"id":"a","type":"text","text":"say \\"height\\":1 é","x":0,"y":0,"width":100,"height":50},\n'
    '\t\t{"id":"b","type":"text","text":"b","x":0,"y":100,"width":100,"height":50,"color":"2"},\n'
    '\t\t{"id":"g","type":"group","label":"G","x":-10,"y":-10,"width":120,"height":170},\n'
    '\t\t{"id":"f","type":"file","file":"x.md","x":500,"y":0,"width":100,"height":100}\n'
    '\t],\n\t"edges":[]\n}'
)


def node(id, x, y, w, h, type="text"):
    return {"id": id, "type": type, "x": x, "y": y, "width": w, "height": h}


class SuggestedHeight(unittest.TestCase):
    def test_adds_15_then_rounds_up_to_ten(self):
        self.assertEqual(cf.suggested_height(100), 120)  # 115
        self.assertEqual(cf.suggested_height(95), 110)  # exactly 110
        self.assertEqual(cf.suggested_height(96), 120)  # 111
        self.assertEqual(cf.suggested_height(8593), 8610)


class Layout(unittest.TestCase):
    def test_overlap_between_plain_nodes_only(self):
        nodes = [node("a", 0, 0, 100, 100), node("b", 50, 50, 100, 100), node("c", 100, 0, 50, 50)]
        self.assertEqual(cf.find_overlaps(nodes), [("a", "b")])

    def test_touching_edges_do_not_overlap(self):
        self.assertEqual(cf.find_overlaps([node("a", 0, 0, 10, 10), node("b", 10, 0, 10, 10)]), [])

    def test_group_is_not_an_overlap_with_its_children(self):
        nodes = [node("g", 0, 0, 100, 100, "group"), node("a", 10, 10, 10, 10)]
        self.assertEqual(cf.find_overlaps(nodes), [])

    def test_group_overflow_only_for_partial_intersection(self):
        nodes = [
            node("g", 0, 0, 100, 100, "group"),
            node("in", 10, 10, 10, 10),
            node("cross", 90, 90, 50, 50),
            node("out", 300, 300, 10, 10),
        ]
        self.assertEqual(cf.find_group_overflows(nodes), [("cross", "g")])

    def test_group_nested_inside_group_is_fine(self):
        nodes = [node("g", 0, 0, 100, 100, "group"), node("h", 10, 10, 10, 10, "group")]
        self.assertEqual(cf.find_group_overflows(nodes), [])


class SetHeights(unittest.TestCase):
    def test_changes_only_the_height_value_bytes(self):
        out = cf.set_heights(RAW, {"a": 120})
        self.assertEqual(out, RAW.replace('"width":100,"height":50},\n\t\t{"id":"b"', '"width":100,"height":120},\n\t\t{"id":"b"'))

    def test_ignores_escaped_height_inside_text(self):
        out = json.loads(cf.set_heights(RAW, {"a": 120}))
        self.assertEqual(out["nodes"][0]["text"], 'say "height":1 é')

    def test_refuses_an_edit_it_cannot_verify(self):
        raw = '{"nodes":[{"id":"a","meta":{"height":1},"height":2}],"edges":[]}'
        with self.assertRaises(ValueError):
            cf.set_heights(raw, {"a": 9})

    def test_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            cf.set_heights(RAW, {"nope": 9})


def ok(**measured):
    return {"nodes": {k: {"content": v} for k, v in measured.items()}, "restored": True}


class Run(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.file = self.base / "t.canvas"
        self.file.write_text(RAW, encoding="utf-8")
        self.lines = []

    def run_tool(self, result, apply=False, during=None, path="t.canvas"):
        def fake_eval(code, vault, timeout):
            if "measureNodes" in code:
                if during:
                    during()
                return result
            return str(self.base)

        return cf.run(path, vault=None, apply=apply, eval_js=fake_eval, emit=self.lines.append)

    def text(self):
        return "\n".join(self.lines)

    def heights(self):
        return [n["height"] for n in json.loads(self.file.read_text(encoding="utf-8"))["nodes"]]

    def test_without_apply_never_writes_and_prints_heights(self):
        self.assertEqual(self.run_tool(ok(a=100, b=95)), 0)
        self.assertEqual(self.file.read_text(encoding="utf-8"), RAW)
        self.assertRegex(self.text(), r"a\s+50\s+100\s+120")
        self.assertRegex(self.text(), r"b\s+50\s+95\s+110")

    def test_apply_writes_only_heights(self):
        self.assertEqual(self.run_tool(ok(a=100, b=95), apply=True), 0)
        before, after = json.loads(RAW), json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual([n["height"] for n in after["nodes"]], [120, 110, 170, 100])
        for n in before["nodes"] + after["nodes"]:
            n.pop("height")
        self.assertEqual(before, after)

    def test_zero_is_a_failure_and_is_not_written(self):
        result = ok(b=95)
        result["nodes"]["a"] = {"content": 0}
        self.assertEqual(self.run_tool(result, apply=True), 1)
        self.assertEqual(self.heights()[:2], [50, 110])
        self.assertRegex(self.text(), r"FAILED.*\n  a: measured 0  \(current 50\)")

    def test_error_and_missing_nodes_are_failures(self):
        result = ok(b=95)
        self.assertEqual(self.run_tool(result), 1)  # a is missing from the result
        self.assertIn("no result", self.text())
        self.lines.clear()
        result["nodes"]["a"] = {"error": "not rendered"}
        self.assertEqual(self.run_tool(result), 1)
        self.assertIn("not rendered", self.text())

    def test_apply_refuses_when_file_changed_during_measuring(self):
        changed = RAW.replace('"x":500', '"x":501')
        code = self.run_tool(ok(a=100, b=95), apply=True, during=lambda: self.file.write_text(changed, encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(self.file.read_text(encoding="utf-8"), changed)
        self.assertIn("changed during measuring", self.text())

    def test_changed_file_without_apply_is_also_reported(self):
        changed = RAW.replace('"x":500', '"x":501')
        code = self.run_tool(ok(a=100, b=95), during=lambda: self.file.write_text(changed, encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertIn("changed during measuring", self.text())

    def test_not_restored_is_a_failure(self):
        result = ok(a=100, b=95)
        result["restored"] = False
        self.assertEqual(self.run_tool(result), 1)
        self.assertIn("not restored", self.text())

    def test_says_when_a_hidden_window_was_shown_for_the_run(self):
        result = ok(a=100, b=95)
        result["shownForRun"] = True
        self.assertEqual(self.run_tool(result), 0)
        self.assertIn("shown without focus", self.text())

    def test_layout_warnings_use_current_and_suggested_heights(self):
        # a grows to 120 and reaches b at y=100; b grows to 110 and leaves group g (ends y=160).
        self.assertEqual(self.run_tool(ok(a=100, b=95)), 0)
        text = self.text()
        self.assertRegex(text, r"(?s)Layout now:.*overlaps: none.*Layout with suggested heights:.*a overlaps b")
        self.assertIn("b sticks out of group g", text)
        self.assertIn("labels", text)

    def test_absolute_path_is_mapped_into_the_vault(self):
        self.assertEqual(self.run_tool(ok(a=100, b=95), path=str(self.file)), 0)

    def test_path_outside_vault_is_rejected(self):
        with self.assertRaises(cf.ToolError):
            self.run_tool(ok(a=100), path="/nowhere/else.canvas")


class Main(unittest.TestCase):
    def test_bad_canvas_data_exits_2_without_traceback(self):
        def broken(*args, **kwargs):
            raise ValueError("the edit would change more than node heights")

        original, cf.run = cf.run, broken
        self.addCleanup(setattr, cf, "run", original)
        sys.argv = ["canvas_fit.py", "x.canvas"]
        self.assertEqual(cf.main(), 2)


if __name__ == "__main__":
    unittest.main()
