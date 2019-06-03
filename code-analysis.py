import ctypes
import os
import glob
import re
import itertools
import git
import argparse
import _locale
# Этот хак позволяет позволяет функциям "open" из модуля git
# открывать файл с кодировкой utf8 по умолчанию
_locale._getdefaultlocale = (lambda *args: ['ru_RU', 'utf8'])

parser = argparse.ArgumentParser()
parser.add_argument('--src-root', dest='src_root', action='store')
args = parser.parse_args()

src = args.src_root
assert src, "Не указана папка с исходниками обработки"
assert os.path.isdir(src), "Не найдена папка с исходниками обработки"
    
log_file = 'Build/code-analysis.log'
tag = '.*Метод присутствует в клиентском и серверном модулях.*'
client_module_name = 'МодульОбъектаКлиент'

re_method_start = r'^\s*(Функция|Процедура)\s+([A-Яа-я\w]+).*'
re_method_end = r'^\s*(?:КонецФункции|КонецПроцедуры).*'
re_return = r'\s*Возврат'
re_directive = r'\s*&([A-Яа-я\w]+)'

class Epf():
    def __init__(self):
        self.modules = []
        self.servermodule = None
        self.clientmodule = None

class Module():
    def __init__(self, full_name):
        self.full_name = full_name
        self.methods = {}
    def __repr__(self):
        return self.full_name

class Method():
    def __init__(self, start, type):
        self.start = start
        self.end = 0
        self.type = type
        self.lines = []
        self.tag = False
        self.has_return = False
        self.directive = ''
    def __repr__(self):
        return "{}: {}-{}".format(self.type, self.start, self.end)


def parse_modules():
    epf = Epf()
    for bsl_full_name in glob.iglob(src + '/**/*.bsl', recursive=True):
        bsl_full_name = os.path.normpath(bsl_full_name)
        module = Module(bsl_full_name)
        epf.modules.append(module)
        if client_module_name in bsl_full_name:
            epf.clientmodule = module
        if 'ObjectModule' in bsl_full_name:
            epf.servermodule = module
        with open(module.full_name, mode='r', encoding='utf-8-sig') as file:
            lines = file.readlines()
            parse_module(module.methods, lines)
    return epf

def parse_module(methods, lines):
    in_method = False
    directive = ""
    for i, line in enumerate(lines):
        match = re.match(re_method_start, line)
        method: Method
        if match:
            method = Method(start=i, type=match.groups()[0])
            methods[match.groups()[1]] = method
            method.directive = directive    
            in_method = True
        elif re.match(re_method_end, line):
            method.end = i
            in_method = False
            directive = ""
        elif in_method:
            if re.match(re_return, line):
                method.has_return = True
            if re.match(tag, line):
                method.tag = True
            method.lines.append(line)
        else: # not in method
            directive_match = re.match(re_directive, line)
            if directive_match:
                directive = directive_match.groups()[0]    

def check_returns(epf, diff):
    for module in epf.modules:
        for method_name, method in module.methods.items():
            if method.type == 'Функция' and not method.has_return:
                yield ('Нет возврата у функции {} в модуле {}'.
                       format(method_name, module.full_name), 
                       in_diff(method, diff, module))

def check_directive(epf, diff):
    managed_forms = filter(lambda x: re.match(".*Форма.bsl$", x.full_name), epf.modules)
    for module in managed_forms:
        for method_name, method in module.methods.items():
            if not method.directive:
                yield ('Нет директивы у функции {} в модуле {}'.
                       format(method_name, module.full_name), 
                       in_diff(method, diff, module))

def check_client_server_methods(epf, diff):
    c_methods = {x:y for x,y in epf.clientmodule.methods.items() if y.tag}
    s_methods = {x:y for x,y in epf.servermodule.methods.items() if y.tag}
    for method_name in set(c_methods) - set(s_methods):
        yield ('Не найден серверный метод: ' + method_name,
               in_diff(c_methods[method_name], diff, epf.clientmodule))
    for method_name in set(s_methods) - set(c_methods):
        yield ('Не найден клиентский метод: ' + method_name,
               in_diff(s_methods[method_name], diff, epf.servermodule))
    for method_name in set(c_methods) & set(s_methods):
        s_lines_without_spaces = [re.sub(r'\s+','',x) for x in s_methods[method_name].lines]
        c_lines_without_spaces = [re.sub(r'\s+','',x) for x in c_methods[method_name].lines]
        if c_lines_without_spaces != s_lines_without_spaces:
            yield ('Метод отличается на клиенте и сервере: ' + method_name, 
                   in_diff(c_methods[method_name], diff, epf.clientmodule) or 
                   in_diff(s_methods[method_name], diff, epf.servermodule))

def in_diff(method, diff, module):
    try:
        return set(range(method.start, method.end)) & diff[module.full_name] != set()
    except:
        return False

def git_diff():
    repo_path = os.path.abspath(os.path.join(src ,"../..")) 
    repo = git.Repo(repo_path)
    changes = {}
    # TODO сейчас сравнивает HEAD c HEAD^ и парсит '-'. 
    # Наверное логичнее сравнивать HEAD^ c HEAD и парсить '+'
    HEAD = repo.head.commit
    all_bsl_changes = HEAD.diff('HEAD^', paths='*.bsl', create_patch=True)
    for file_changes in all_bsl_changes:
        patches = re.findall(r'@@(.*)@@', str(file_changes))
        file_path = os.path.normpath(file_changes.a_path)
        changes[file_path] = set()
        for patch in patches:
            groups = re.search(r'\-(\d+)(?:,(\d*))?', patch).groups()
            start_line = int(groups[0])
            num_lines = int(groups[1]) if groups[1] else 1
            end_line = start_line + num_lines - 1
            changes[file_path] |= set(range(start_line, end_line))
    return changes


diff = git_diff()
epf = parse_modules()
all_errors = itertools.chain(
        check_returns(epf, diff), 
        check_directive(epf, diff), 
        check_client_server_methods(epf, diff)
    )
all_errors = list(all_errors)
errors_in_diff = [x for x in all_errors if x[1]]
errors_not_in_diff = [x for x in all_errors if not x[1]]

with open(log_file, mode='w', encoding='utf-8') as file:
    file.write('Проблемы в текущем коммите:\n')
    for err_text, in_diff in errors_in_diff:
        file.write(err_text + '\n')
    file.write('Остальные проблемы:\n')
    for err_text, in_diff in errors_not_in_diff:
        file.write(err_text + '\n')
if len(errors_in_diff):
    ctypes.windll.user32.MessageBoxW(0, 'Подробности в ' + log_file,
                                     'Обнаружены проблемы в коммите', 1)