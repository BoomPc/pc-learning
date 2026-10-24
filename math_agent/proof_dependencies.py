"""Expose declared proof dependencies to reviewers; never certify mathematical truth."""

def review_dependencies(source, solutions):
    conditions = {c.id:c for c in source.conditions}
    ancestors = {}
    transfers = []
    for solution in solutions:
        for index, step in enumerate(solution.steps, 1):
            current = f'{solution.question_id}:S{index}'
            dependencies = set()
            for basis in step.basis_ids:
                if basis in conditions:
                    dependencies.add(basis)
                elif basis in ancestors:
                    dependencies.update(ancestors[basis])
                else:
                    raise ValueError(f'{current}: 未知或尚未出现的依据 {basis}')
                cross = ':' in basis and basis.split(':',1)[0] != solution.question_id
                inherited = {basis} if basis in conditions else ancestors.get(basis,set())
                scoped = sorted(c for c in inherited if conditions[c].question_ids and solution.question_id not in conditions[c].question_ids)
                if cross or scoped:
                    transfers.append({'step':current,'basis':basis,
                        'source_conditions':sorted(inherited),'out_of_scope_conditions':scoped})
            ancestors[current] = dependencies
    return {'transfers':transfers,'limits':'只追踪声明的basis_ids；遗漏依据、图示假设和数学真伪仍须独立核验。跨问引用并非自动错误；必须证明依赖条件在当前问仍成立或独立重推，数值相同不能替代证明。'}
