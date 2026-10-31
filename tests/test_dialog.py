"""UI checks run with KiCad's bundled Python (wxPython + pcbnew)."""
import importlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, Mock

HAS_HOST = importlib.util.find_spec('wx') is not None and importlib.util.find_spec('pcbnew') is not None


class QuietProgress:
    instances=[]
    def __init__(self,*args,**kwargs):
        self.closed=False
        self.values=[]
        self.instances.append(self)
    def Update(self,value,message): self.values.append(value)
    def Destroy(self): self.closed=True


@unittest.skipUnless(HAS_HOST, 'Requires KiCad Python with wxPython')
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.App(False)
        package = types.ModuleType('coil_ui_test')
        package.__path__ = [str(Path(__file__).resolve().parents[1] / 'Src/plugins')]
        sys.modules[package.__name__] = package
        cls.action = importlib.import_module('coil_ui_test.rogowski_action')

    def setUp(self):
        QuietProgress.instances=[]
        self.progress_patch=patch.object(self.wx,'ProgressDialog',QuietProgress)
        self.progress_patch.start()
        self.addCleanup(self.progress_patch.stop)
        self.dialog = self.action.Parameters(None, 2)
        self.dialog.Layout()

    def tearDown(self):
        self.dialog.Destroy()
        self.app.ProcessPendingEvents()

    def test_entries_keep_native_single_line_height(self):
        for entry in self.dialog.entries.values():
            self.assertLessEqual(entry.GetSize().height, entry.GetBestSize().height + 2)
            self.assertEqual(entry.GetSize().width, self.dialog.FromDIP(110))
        self.assertLessEqual(self.dialog.generate_button.GetRect().bottom,
                             self.dialog.GetClientSize().height)

    def test_generate_requires_successful_validation_and_reuses_model(self):
        d=self.dialog
        self.assertFalse(d.generate_button.IsEnabled())
        with patch.object(d,'EndModal') as end:
            d.on_generate(None)
            end.assert_not_called()
        with patch.object(self.action.geometry,'build',wraps=self.action.geometry.build) as build:
            d.validate_parameters()
            self.assertTrue(d.generate_button.IsEnabled())
            self.assertIsNotNone(d.get_validated_geometry())
            with patch.object(d,'EndModal') as end:
                d.on_generate(None)
                end.assert_called_once_with(self.wx.ID_OK)
            self.assertEqual(build.call_count,1)
        self.assertTrue(QuietProgress.instances[-1].closed)
        self.assertEqual(QuietProgress.instances[-1].values[-1],100)

    def test_editing_any_parameter_or_option_requires_revalidation(self):
        d=self.dialog
        for key,entry in d.entries.items():
            with self.subTest(key=key):
                d.validate_parameters()
                self.assertTrue(d.generate_button.IsEnabled())
                value=entry.GetValue()
                entry.SetValue(value+' ')
                self.assertFalse(d.generate_button.IsEnabled())
                self.assertIsNone(d.validated_geometry)
                entry.SetValue(value)
        for option in (d.center_hole,d.outline):
            d.validate_parameters()
            self.assertTrue(d.generate_button.IsEnabled())
            option.SetValue(not option.GetValue())
            event=self.wx.CommandEvent(self.wx.wxEVT_CHECKBOX,option.GetId())
            event.SetEventObject(option)
            option.GetEventHandler().ProcessEvent(event)
            self.assertFalse(d.generate_button.IsEnabled())

    def test_overlap_error_keeps_inputs_and_generation_disabled(self):
        d=self.dialog
        for key,value in dict(ri1=10,ri2=11,ro1=14,ro2=15,bend_radius=1.4).items():
            d.entries[key].SetValue(str(value))
        d.entries['width'].SetValue('2.0')
        d.validate_parameters()
        self.assertFalse(d.generate_button.IsEnabled())
        self.assertIsNone(d.validated_geometry)
        self.assertEqual(d.entries['width'].GetValue(),'2.0')
        self.assertIn('겹',d.validation_status.GetLabel())
        self.assertTrue(QuietProgress.instances[-1].closed)

    def test_stale_cached_values_cannot_be_generated(self):
        d=self.dialog
        d.validate_parameters()
        d.entries['cx'].ChangeValue('101')  # Deliberately bypass the text event.
        with self.assertRaisesRegex(ValueError,'다시 검증'):
            d.get_validated_geometry()
        self.assertFalse(d.generate_button.IsEnabled())

    def test_run_generates_the_validated_model_without_rebuilding(self):
        self.dialog.validate_parameters()
        geometry=self.dialog.get_validated_geometry()
        board=Mock()
        board.GetCopperLayerCount.return_value=2
        dialog=Mock()
        dialog.ShowModal.return_value=self.wx.ID_OK
        dialog.get_validated_geometry.return_value=geometry
        with patch.object(self.action,'Parameters',return_value=dialog), \
             patch.object(self.action.pcbnew,'GetBoard',return_value=board), \
             patch.object(self.action.pcbnew,'Refresh') as refresh, \
             patch.object(self.wx,'MessageBox') as message, \
             patch.object(self.action,'apply_geometry',return_value=1) as apply, \
             patch.object(self.action.geometry,'build',side_effect=AssertionError('Must reuse validation')):
            self.action.RogowskiAction().Run()
            self.assertIs(apply.call_args.args[0],board)
            self.assertIs(apply.call_args.args[1],geometry)
            refresh.assert_called_once()
            self.assertEqual(message.call_args.args[-1],self.wx.OK|self.wx.ICON_INFORMATION)
        dialog.Destroy.assert_called_once()

    def test_outline_conflict_fails_before_build_without_board_mutation(self):
        d=self.dialog
        board=Mock()
        shape=Mock()
        shape.GetLayer.return_value=self.action.pcbnew.Edge_Cuts
        board.GetDrawings.return_value=[shape]
        d.board=board
        d.outline.SetValue(True)
        with patch.object(self.action.geometry,'build') as build:
            d.validate_parameters()
            build.assert_not_called()
        board.Add.assert_not_called()
        self.assertFalse(d.generate_button.IsEnabled())
        self.assertIn('Edge.Cuts',d.validation_status.GetLabel())

    def test_every_focus_highlight_renders_and_clears(self):
        wx = self.wx
        for key, entry in self.dialog.entries.items():
            with self.subTest(key=key):
                focus = wx.FocusEvent(wx.wxEVT_SET_FOCUS, entry.GetId())
                focus.SetEventObject(entry)
                entry.GetEventHandler().ProcessEvent(focus)
                preview = self.dialog.preview
                self.assertEqual(preview.active_key, key)
                self.assertTrue(self.dialog.focus_help.GetLabel())
                bitmap = wx.Bitmap(*preview.GetClientSize())
                dc = wx.MemoryDC(bitmap)
                preview.draw(dc)
                dc.SelectObject(wx.NullBitmap)
                # Every parameter must produce visible yellow highlight pixels.
                pixels = bitmap.ConvertToImage().GetData()
                self.assertIn(bytes((255, 224, 102)), pixels)
                blur = wx.FocusEvent(wx.wxEVT_KILL_FOCUS, entry.GetId())
                blur.SetEventObject(entry)
                entry.GetEventHandler().ProcessEvent(blur)
                self.assertIsNone(preview.active_key)


if __name__ == '__main__':
    unittest.main()
