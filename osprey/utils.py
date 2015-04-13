from __future__ import print_function, absolute_import, division
import os.path
import sys
import contextlib
from datetime import datetime
from sklearn.pipeline import Pipeline

from .eval_scopes import import_all_estimators

__all__ = ['dict_merge']


def dict_merge(base, top):
    """Recursively merge two dictionaries, with the elements from `top`
    taking precedence over elements from `top`.

    Returns
    -------
    out : dict
        A new dict, containing the merged records.
    """
    out = dict(top)
    for key in base:
        if key in top:
            if isinstance(base[key], dict) and isinstance(top[key], dict):
                out[key] = dict_merge(base[key], top[key])
        else:
            out[key] = base[key]
    return out


@contextlib.contextmanager
def in_directory(path):
    """Context manager (with statement) that changes the current directory
    during the context.
    """
    curdir = os.path.abspath(os.curdir)
    os.chdir(path)
    yield
    os.chdir(curdir)


@contextlib.contextmanager
def prepend_syspath(path):
    """Contect manager (with statement) that prepends path to sys.path"""
    sys.path.insert(0, path)
    yield
    sys.path.pop(0)


class Unbuffered(object):
    # used to turn off output buffering
    # http://stackoverflow.com/questions/107705/python-output-buffering

    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def format_timedelta(td_object):
    """Format a timedelta object for display to users

    Returns
    -------
    str
    """
    def get_total_seconds(td):
        # timedelta.total_seconds not in py2.6
        return (td.microseconds +
                (td.seconds + td.days * 24 * 3600) * 1e6) / 1e6

    seconds = int(get_total_seconds(td_object))
    periods = [('year',    60*60*24*365),
               ('month',   60*60*24*30),
               ('day',     60*60*24),
               ('hour',    60*60),
               ('minute',  60),
               ('second',  1)]

    strings = []
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            if period_value == 1:
                strings.append("%s %s" % (period_value, period_name))
            else:
                strings.append("%s %ss" % (period_value, period_name))

    return ", ".join(strings)


def current_pretty_time():
    return datetime.now().strftime("%B %d, %Y %l:%M %p")


def _squeeze_time(t):
    """Remove .1s to the time under Windows: this is the time it take to
    stat files. This is needed to make results similar to timings under
    Unix, for tests
    """
    if sys.platform.startswith('win'):
        return max(0, t - .1)
    else:
        return t


def short_format_time(t):
    t = _squeeze_time(t)
    if t > 60:
        return "%4.1fmin" % (t / 60.)
    else:
        return " %5.1fs" % (t)


def mock_module(name):

    class MockModule(object):
        def __cal__(self, *args, **kwargs):
            raise ImportError('no module named %s' % name)

        def __getattr__(self, *args, **kwargs):
            raise ImportError('no module named %s' % name)

    return MockModule()


def join_quoted(values, quote="'"):
    return ', '.join("%s%s%s" % (quote, e, quote) for e in values)


def expand_path(path, base='.'):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return path


def is_msmbuilder_estimator(estimator):
    try:
        import msmbuilder
    except ImportError:
        return False
    msmbuilder_estimators = import_all_estimators(msmbuilder).values()

    out = estimator.__class__ in msmbuilder_estimators
    if isinstance(estimator, Pipeline):
        out = any(step.__class__ in msmbuilder_estimators
                  for name, step in estimator.steps)
    return out


def check_arrays(*arrays, **options):
    """Check that all arrays have consistent first dimensions.

    Checks whether all objects in arrays have the same shape or length.
    By default lists and tuples are converted to numpy arrays.

    It is possible to enforce certain properties, such as dtype, continguity
    and sparse matrix format (if a sparse matrix is passed).

    Converting lists to arrays can be disabled by setting ``allow_lists=True``.
    Lists can then contain arbitrary objects and are not checked for dtype,
    finiteness or anything else but length. Arrays are still checked
    and possibly converted.


    Parameters
    ----------
    *arrays : sequence of arrays or scipy.sparse matrices with same shape[0]
        Python lists or tuples occurring in arrays are converted to 1D numpy
        arrays, unless allow_lists is specified.

    sparse_format : 'csr' | 'csc' | 'dense' | list,  None by default.
        If not None, scipy.sparse matrices will be converted to the format(s)
        specified, or left alone if they are already an accepted format.
        If multiple sparse formats are accepted, pass them in via a list.
        This list can contain 'csc' and/or 'csr.'
        If 'dense', an error is raised when a sparse array is
        passed.

    copy : boolean, False by default
        If copy is True, ensure that returned arrays are copies of the original
        (if not already converted to another format earlier in the process).

    check_ccontiguous : boolean, False by default
        Check that the arrays are C contiguous

    dtype : a numpy dtype instance, None by default
        Enforce a specific dtype.

    allow_lists : bool
        Allow lists of arbitrary objects as input, just check their length.
        Disables

    allow_nans : boolean, False by default
        Allows nans in the arrays
    """
    sparse_format = options.pop('sparse_format', None)
    _validate_sparse_format_options(sparse_format)

    copy = options.pop('copy', False)
    check_ccontiguous = options.pop('check_ccontiguous', False)
    dtype = options.pop('dtype', None)
    allow_lists = options.pop('allow_lists', False)
    allow_nans = options.pop('allow_nans', False)

    if options:
        raise TypeError("Unexpected keyword arguments: %r" % options.keys())

    if len(arrays) == 0:
        return None

    n_samples = _num_samples(arrays[0])

    checked_arrays = []
    for array in arrays:
        array_orig = array
        if array is None:
            # special case: ignore optional y=None kwarg pattern
            checked_arrays.append(array)
            continue
        size = _num_samples(array)

        if size != n_samples:
            raise ValueError("Found array with dim %d. Expected %d"
                             % (size, n_samples))

        if not allow_lists or hasattr(array, "shape"):
            if sp.issparse(array):
                array = _check_sparse_format(array, sparse_format)
                if check_ccontiguous:
                    array.data = np.ascontiguousarray(array.data, dtype=dtype)
                else:
                    array.data = np.asarray(array.data, dtype=dtype)
                if not allow_nans:
                    _assert_all_finite(array.data)
            else:
                if check_ccontiguous:
                    array = np.ascontiguousarray(array, dtype=dtype)
                else:
                    array = np.asarray(array, dtype=dtype)
                if not allow_nans:
                    _assert_all_finite(array)

            if array.ndim >= 3:
                raise ValueError("Found array with dim %d. Expected <= 2" %
                                 array.ndim)

        if copy and array is array_orig:
            array = array.copy()
        checked_arrays.append(array)

    return checked_arrays


def _validate_sparse_format_options(sparse_format):
    """Validates sparse_format options for `check_arrays`"""
    valid_sparse_formats = ('csr', 'csc')
    valid_sparse_options = ('csr', 'csc', 'dense', None)

    is_valid_format = sparse_format in valid_sparse_options
    contains_valid_formats = (
        hasattr(sparse_format, '__iter__') and
        all([f in valid_sparse_formats for f in sparse_format])
    )

    # Validate sparse_format option
    if not(is_valid_format or contains_valid_formats):
        raise ValueError('Unexpected sparse format(s): %r' % sparse_format)



def _num_samples(x):
    """Return number of samples in array-like x."""
    if not hasattr(x, '__len__') and not hasattr(x, 'shape'):
        raise TypeError("Expected sequence or array-like, got %r" % x)
    return x.shape[0] if hasattr(x, 'shape') else len(x)
