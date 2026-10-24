"""Restricted geometry edits: never accept or regenerate mathematical solutions."""
import copy
from typing import Literal
from pydantic import Field
from .contracts import Strict
from .jsxgraph.spec import Geometry, Controls, View

class Edit(Strict):
    tab: int = Field(ge=0,le=11)
    upsert: list[Geometry] = Field(default_factory=list,max_length=120)
    remove: list[str] = Field(default_factory=list,max_length=120)
    viewport: Literal['manual','fit_points'] | None = None
    bounding_box: list[float] | None = Field(default=None,min_length=4,max_length=4)
    view: View | None = None
    axis: bool | None = None
    controls: Controls | None = None

class DiagramPatch(Strict):
    edits: list[Edit] = Field(min_length=1,max_length=12)

def apply_patch(raw, previous, audit=None, allowed_tabs=None):
    value=DiagramPatch.model_validate(raw)
    result=previous.model_copy(deep=True)
    seen=set()
    for edit in value.edits:
        if edit.tab in seen or edit.tab>=len(result.spec['tabs']): raise ValueError('重复或不存在的小问tab')
        if allowed_tabs is not None and edit.tab not in allowed_tabs:
            raise ValueError('局部纠错不能修改错误清单以外的画板')
        seen.add(edit.tab)
        tab=result.spec['tabs'][edit.tab]; board=tab['board']
        objects={o['id']:o for o in board['objects']}
        ids=[o.id for o in edit.upsert]
        if len(ids)!=len(set(ids)) or len(edit.remove)!=len(set(edit.remove)) or set(ids)&set(edit.remove):
            raise ValueError('对象增改/删除编号重复或冲突')
        if not set(edit.remove)<=objects.keys(): raise ValueError('不能删除不存在的对象')
        for key in edit.remove: del objects[key]
        for obj in edit.upsert: objects[obj.id]=obj.model_dump(exclude_none=True)
        board['objects']=list(objects.values())
        for key in ('viewport','bounding_box','axis'):
            if key in edit.model_fields_set: board[key]=getattr(edit,key)
        if 'view' in edit.model_fields_set:
            if edit.view is None or 'bounding_box' in edit.model_fields_set:
                raise ValueError('具名view不能为空，且不能与bounding_box同时修改')
            board.pop('bounding_box',None)
            board.pop('view',None)
            board['bounding_box']=edit.view.box()
        if 'controls' in edit.model_fields_set:
            if edit.controls is None: tab.pop('controls',None)
            else:tab['controls']=edit.controls.model_dump(exclude_none=True)
    from .parent_binding import bind_parent_roles
    result.spec,_=bind_parent_roles(result.spec,audit)
    from .rendering import strict_spec
    strict_spec(result.spec) # Reject invalid fields, dangling parents, unsafe expressions before rendering.
    return result
