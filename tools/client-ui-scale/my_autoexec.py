# Client-side experiment/feature: 200% UI via triui.UILib.desktopScale.
# Executed by script/sys/autoexec.py before script/run.py.  Delete this file to
# roll back; no compiled.code or bin changes are involved.
#
# desktopScale=0.5 makes the virtual desktop half the window size (UI 2x).
# It is applied after LoadLayers (login) and around GoStation/GoInflight
# (in-game), because the device/window is recreated on session change.

import blue
import os

_PID = os.getpid()
_SEQ = [0]


def _log(msg):
    try:
        _SEQ[0] += 1
        f = blue.ResFile()
        f.Create('cache:/ui_scale_%s_%03d.txt' % (_PID, _SEQ[0]))
        f.Write(str(msg))
        f.Close()
    except Exception:
        pass


def _set_scale(where):
    try:
        import __builtin__
        eve = __builtin__.eve
        u = eve.triapp.uilib
        before = getattr(u, 'desktopScale', 'missing')
        u.desktopScale = 0.5
        d = u.desktop
        _log('%s: desktopScale %r -> %r desktop=%dx%d'
             % (where, before, getattr(u, 'desktopScale', 'missing'), d.width, d.height))
    except Exception, e:
        _log('%s: scale error %r' % (where, e))


_log('module start pid=%s' % _PID)
try:
    import __builtin__
    eve = __builtin__.eve
    sm = __builtin__.sm
    eve.LocalSvc('gameui')
    svc = sm.services['gameui']
    cls = svc.__class__
    _log('real gameui service: %r class=%r' % (svc, cls))

    def _wrap(name, pre=False, post=True):
        orig = getattr(cls, name)

        def _patched(self, *args, **kwargs):
            if pre:
                _set_scale(name + ':pre')
            result = orig(self, *args, **kwargs)
            if post:
                _set_scale(name + ':post')
            return result

        setattr(cls, name, _patched)
        _log('patched class %s' % name)

    _wrap('LoadLayers', pre=False, post=True)
    _wrap('GoStation', pre=True, post=True)
    _wrap('GoInflight', pre=True, post=True)
    _wrap('OnSessionChanged', pre=False, post=True)
except Exception, e:
    _log('module error: %r' % (e,))
