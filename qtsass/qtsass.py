import sass
import argparse
import logging
import os
import re
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Conformer(object):
    '''Base class for all Text transformations'''

    def to_css(self, qss):
        '''Transform some qss to valid scss'''
        return NotImplemented

    def to_qss(self, css):
        '''Transform some css to valid qss'''
        return NotImplemented


class NotConformer(Conformer):
    '''Handle QSS "!" in selectors'''

    def to_css(self, qss):
        '''Replaces "!" not in selectors with "_qnot_"'''

        return qss.replace(':!', ':_qnot_')

    def to_qss(self, css):
        '''Replaces "_qnot_" in selectors with "!"'''

        return css.replace(':_qnot_', ':!')


class NestedSelectorsConformer(Conformer):
    '''Handle QSS Nested selectors like ::item:hover'''

    pattern = re.compile(r'::[A-Za-z0-9-_!]+((?:\:[A-Za-z0-9-_!]+)+)')

    def to_css(self, qss):
        '''Replaces ":" in nested selectors with "_qcolon_"'''

        conformed = qss
        matches = self.pattern.findall(qss)
        for match in matches:
            replacement = match.replace(':', '_qcolon_')
            conformed = conformed.replace(match, replacement, 1)
        return conformed

    def to_qss(self, css):
        '''Replaces "_qcolon_" with ":"'''

        return css.replace('_qcolon_', ':')


conformers = [c() for c in Conformer.__subclasses__() if c is not Conformer]


def css_conform(input_str):
    '''Conform qss to valid scss. Runs the to_css method of all Conformer
    subclasses on the input_str.

    :param input_str: QSS string
    :returns: Valid SCSS string
    '''

    conformed = input_str
    for conformer in conformers:
        conformed = conformer.to_css(conformed)

    return conformed


def qt_conform(input_str):
    '''Conform css to valid qss. Runs the to_qss method of all Conformer
    subclasses on the input_str.

    :param input_str: CSS string
    :returns: Valid QSS string
    '''

    conformed = input_str
    for conformer in conformers:
        conformed = conformer.to_qss(conformed)
    return conformed


def rgba(r, g, b, a):
    result = "rgba({}, {}, {}, {}%)"
    if isinstance(r, sass.SassNumber):
        return result.format(
            int(r.value),
            int(g.value),
            int(b.value),
            int(a.value * 100)
        )
    elif isinstance(r, float):
        return result.format(int(r), int(g), int(b), int(a * 100))


def rgba_from_color(color):
    """
    Conform rgba
    :type color: sass.SassColor
    """
    return rgba(color.r, color.g, color.b, color.a)


def qlineargradient(x1, y1, x2, y2, stops):
    """
    :type x1: sass.SassNumber
    :type y1: sass.SassNumber
    :type x2: sass.SassNumber
    :type y2: sass.SassNumber
    :type stops: sass.SassList
    :return:
    """
    stops_str = ""
    for stop in stops[0]:
        pos, color = stop[0]
        stops_str += " stop: {} {}".format(pos.value, rgba_from_color(color))

    return "qlineargradient(x1:{}, y1:{}, x2:{}, y2:{} {})".format(
        x1.value,
        y1.value,
        x2.value,
        y2.value,
        stops_str.rstrip(",")
    )


def compile_to_css(input_file):
    logger.debug("Compiling {}...".format(input_file))

    with open(input_file, "r") as f:
        input_str = f.read()

    try:
        return qt_conform(
            sass.compile(
                string=css_conform(input_str),
                source_comments=False,
                custom_functions={
                    'qlineargradient': qlineargradient,
                    'rgba': rgba
                }
            )
        )
    except sass.CompileError as e:
        logging.error("Failed to compile {}:\n{}".format(input_file, e))
    return ""


def compile_to_css_and_save(input_file, dest_file):
    stylesheet = compile_to_css(input_file)
    if dest_file:
        with open(dest_file, 'w') as css_file:
            css_file.write(stylesheet)
            logger.info("Created CSS file {}".format(dest_file))
    else:
        print(stylesheet)


class SourceModificationEventHandler(FileSystemEventHandler):
    def __init__(self, input_file, dest_file, watched_dir):
        super(SourceModificationEventHandler, self).__init__()
        self._input_file = input_file
        self._dest_file = dest_file
        self._watched_dir = watched_dir
        self._watched_extension = os.path.splitext(self._input_file)[1]

    def _recompile(self):
        i = 0
        success = False
        while i < 10 and not success:
            try:
                time.sleep(0.2)
                compile_to_css_and_save(self._input_file, self._dest_file)
                success = True
            except FileNotFoundError:
                i += 1

    def on_modified(self, event):
        # On Mac, event will always be a directory.
        # On Windows, only recompile if event's file has
        #             the same extension as the input file
        we_should_recompile = (
            event.is_directory and
            os.path.samefile(event.src_path, self._watched_dir) or
            os.path.splitext(event.src_path)[1] == self._watched_extension
        )
        if we_should_recompile:
            self._recompile()

    def on_created(self, event):
        if os.path.splitext(event.src_path)[1] == self._watched_extension:
            self._recompile()


def main():
    parser = argparse.ArgumentParser(
        prog="QtSASS",
        description="Compile a Qt compliant CSS file from a SASS stylesheet.",
    )
    parser.add_argument('input', type=str, help="The SASS stylesheet file.")
    parser.add_argument(
        '-o',
        '--output',
        type=str,
        help="The path of the generated Qt compliant CSS file."
    )
    parser.add_argument(
        '-w',
        '--watch',
        action='store_true',
        help=(
            "Whether to watch source file "
            "and automatically recompile on file change."
        )
    )

    args = parser.parse_args()
    compile_to_css_and_save(args.input, args.output)

    if args.watch:
        watched_dir = os.path.abspath(os.path.dirname(args.input))
        event_handler = SourceModificationEventHandler(
            args.input,
            args.output,
            watched_dir
        )
        logging.info("qtsass is watching {}...".format(args.input))
        observer = Observer()
        observer.schedule(event_handler, watched_dir, recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


if __name__ == '__main__':
    main()
