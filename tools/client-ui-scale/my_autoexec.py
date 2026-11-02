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


def _set_scale(where, value):
    try:
        import __builtin__
        eve = __builtin__.eve
        u = eve.triapp.uilib
        before = getattr(u, 'desktopScale', 'missing')
        u.desktopScale = value
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

    def _wrap(name, value, pre=False, post=True):
        orig = getattr(cls, name)

        def _patched(self, *args, **kwargs):
            if pre:
                _set_scale(name + ':pre', value)
            result = orig(self, *args, **kwargs)
            if post:
                _set_scale(name + ':post', value)
            return result

        setattr(cls, name, _patched)
        _log('patched class %s (scale %s)' % (name, value))

    def _session_scale(where):
        try:
            s = eve.session
            if getattr(s, 'stationid', None) is not None or getattr(s, 'solarsystemid', None) is not None:
                value = 0.5
            else:
                value = 1.0
        except Exception:
            value = 1.0
        _set_scale(where, value)

    def _wrap_session(name):
        orig = getattr(cls, name)

        def _patched(self, *args, **kwargs):
            result = orig(self, *args, **kwargs)
            _session_scale(name + ':post')
            return result

        setattr(cls, name, _patched)
        _log('patched class %s (session scale)' % name)

    # Login page stays 1x: splashunderlay.blue is fixed-size and clips at 2x.
    _wrap('LoadLayers', 1.0, pre=False, post=True)
    _wrap('GoLogin', 1.0, pre=True, post=True)
    # Character selection and in-game are 2x.
    _wrap('GoCharacterSelection', 0.5, pre=True, post=True)
    _wrap('GoStation', 0.5, pre=True, post=True)
    _wrap('GoInflight', 0.5, pre=True, post=True)
    _wrap_session('OnSessionChanged')
except Exception, e:
    _log('module error: %r' % (e,))
