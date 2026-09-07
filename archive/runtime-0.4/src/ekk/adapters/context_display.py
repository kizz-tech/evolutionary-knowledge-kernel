"""Optional CLI display projection; never an application or acceptance input."""
from copy import deepcopy


def compact_context(result):
    """Preserve selected knowledge and authority; elide only historical wrappers."""
    output = deepcopy(result)
    schema = output.get('schema')
    if schema == 'ekk.federated-context/0.1':
        output['schema'] = 'ekk.federated-context-display/0.1'
        output['contexts'] = [compact_context(child) for child in output['contexts']]
    elif schema == 'ekk.context/0.1':
        output['schema'] = 'ekk.context-display/0.1'
        for record in output['records']:
            metadata = record['metadata']
            migration = metadata.get('migration')
            # Unknown extension semantics and governing records remain intact.
            if (record.get('source_content') and not record.get('governs')
                    and isinstance(migration, dict)
                    and migration.get('status') == 'historical'
                    and migration.get('adoption') == 'not_adopted'):
                elided = []
                if 'legacy_metadata' in migration:
                    del migration['legacy_metadata']
                    elided.append('migration.legacy_metadata')
                if ('originals' in migration
                        and migration['originals'] == metadata.get('source', {}).get('assets')):
                    del migration['originals']
                    elided.append('migration.originals (identical to source.assets)')
                if elided:
                    record['display_elided_fields'] = elided
        manifest = output['manifest']
        manifest['omitted_count'] = len(manifest.pop('omitted'))
    elif output.get('status') != 'unbound':
        raise ValueError('Unsupported compact context schema')
    output['display_projection'] = {
        'mode': 'compact',
        'full_output': 'Repeat the same command without --compact; omitted records may require a larger --budget.',
        'authority': 'Display only. Record digests identify full canonical bytes, not this projection. Source content is not accepted authority; governs is unchanged.',
    }
    return output
