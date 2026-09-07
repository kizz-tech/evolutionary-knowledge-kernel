"""Bounded UTF-8 Markdown/YAML and the exact published JSON Schema boundary."""
import json
from pathlib import Path
from ekk.assets import schema_directory
import yaml
from jsonschema import Draft202012Validator, FormatChecker

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 64

class _Loader(yaml.SafeLoader):
    pass

def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError('YAML mapping keys must be strings')
        if key in result:
            raise ValueError(f'duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result

_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
_Loader.yaml_implicit_resolvers = {key: [(tag, regex) for tag, regex in entries if tag != 'tag:yaml.org,2002:timestamp'] for key, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()}

class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):return True


def _bounded_graph(value):
    """Reject cycles and bound expanded aliases without expanding the graph."""
    visiting=set();memo={}
    def cost(node, depth):
        if depth > MAX_DEPTH:raise ValueError('YAML nesting exceeds limit')
        if not isinstance(node,(dict,list)):
            return 1,len(str(node).encode('utf-8'))
        identity=id(node)
        if identity in visiting:raise ValueError('cyclic YAML aliases are forbidden')
        if identity in memo:return memo[identity]
        visiting.add(identity);count=1;size=0
        children=(item for pair in node.items() for item in pair) if isinstance(node,dict) else iter(node)
        for child in children:
            child_count,child_size=cost(child,depth+1)
            count+=child_count;size+=child_size
            if count>MAX_NODES or size>MAX_DOCUMENT_BYTES:raise ValueError('expanded YAML exceeds limit')
        visiting.remove(identity);memo[identity]=(count,size)
        return count,size
    cost(value,0)


class MarkdownCodec:
    def __init__(self, schema_dir=None):
        self.schema_dir=Path(schema_dir) if schema_dir else schema_directory()
        self._validators={}

    def validate_schema(self, name, value):
        if name not in ('record','realm','receipt','workspace'):raise ValueError('unsupported schema name')
        if name not in self._validators:
            schema=json.loads((self.schema_dir/(name+'.schema.json')).read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
            self._validators[name]=Draft202012Validator(schema,format_checker=FormatChecker())
        error=next(self._validators[name].iter_errors(value),None)
        if error is not None:raise ValueError(f'{name} schema: {error.message}')

    def load_json(self, raw):
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate JSON key: '+key)
                result[key]=value
            return result
        try:value=json.loads(self._text(raw),object_pairs_hook=pairs)
        except RecursionError as exc:raise ValueError('JSON nesting exceeds limit') from exc
        _bounded_graph(value)
        return value

    def _text(self, raw):
        if not isinstance(raw,bytes) or len(raw)>MAX_DOCUMENT_BYTES:raise ValueError('document exceeds 2 MiB limit')
        return raw.decode('utf-8')

    def _yaml(self, raw, *, allow_aliases=False):
        text=self._text(raw);aliases=False;depth=0;nodes=0;alias_count=0
        try:
            for event in yaml.parse(text,Loader=_Loader):
                nodes+=1
                if nodes>MAX_NODES:raise ValueError('YAML node limit exceeded')
                if isinstance(event,(yaml.events.MappingStartEvent,yaml.events.SequenceStartEvent)):
                    depth+=1
                    if depth>MAX_DEPTH:raise ValueError('YAML nesting exceeds limit')
                elif isinstance(event,(yaml.events.MappingEndEvent,yaml.events.SequenceEndEvent)):depth-=1
                elif isinstance(event,yaml.events.AliasEvent):
                    aliases=True;alias_count+=1
                    if not allow_aliases:raise ValueError('YAML aliases are not supported in current documents')
                    if alias_count>128:raise ValueError('historical YAML alias limit exceeded')
            value=yaml.load(text,Loader=_Loader)
        except yaml.YAMLError as exc:raise ValueError('invalid YAML document') from exc
        if not isinstance(value,dict):raise ValueError('YAML document must be a mapping')
        _bounded_graph(value)
        return value,aliases

    def load_yaml(self, raw, *, allow_aliases=False):
        return self._yaml(raw,allow_aliases=allow_aliases)[0]

    def dump_yaml(self, value):
        _bounded_graph(value)
        raw=yaml.dump(value,Dumper=_Dumper,allow_unicode=True,sort_keys=True).encode('utf-8')
        self._text(raw)
        return raw

    def decode(self, raw, *, allow_aliases=False):
        lines=self._text(raw).splitlines(keepends=True)
        if not lines or lines[0].strip()!='---':raise ValueError('Markdown frontmatter required')
        end=next((i for i in range(1,len(lines)) if lines[i].strip()=='---'),None)
        if end is None:raise ValueError('unterminated frontmatter')
        metadata,aliases=self._yaml(''.join(lines[1:end]).encode(),allow_aliases=allow_aliases)
        result={'metadata':metadata,'body':''.join(lines[end+1:])}
        if aliases:result['serialization_warnings']=['historical YAML aliases read through bounded compatibility decoder; original bytes preserved']
        return result

    def encode(self, metadata, body=''):
        raw=b'---\n'+self.dump_yaml(metadata)+b'---\n'+body.encode('utf-8')
        self._text(raw)
        return raw
