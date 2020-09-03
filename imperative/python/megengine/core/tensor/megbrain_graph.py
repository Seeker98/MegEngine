# -*- coding: utf-8 -*-
# MegEngine is Licensed under the Apache License, Version 2.0 (the "License")
#
# Copyright (c) 2014-2020 Megvii Inc. All rights reserved.
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT ARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
import collections
import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from .. import _imperative_rt
from .._imperative_rt.ops import BackwardGraph
from .._wrap import device as as_device
from ..ops.builtin import OpDef
from .core import OpBase, TensorBase, apply


class Graph(_imperative_rt.ComputingGraph):
    def __init__(self):
        super().__init__()
        self._var_cache = weakref.WeakKeyDictionary()
        self._op_cache = weakref.WeakKeyDictionary()
        self._executor = ThreadPoolExecutor(1)
        self._function = None
        self._future = None

    def _wrap(self, obj):
        if type(obj) is _imperative_rt.VarNode:
            wrapper, cache = VarNode, self._var_cache
        elif type(obj) is _imperative_rt.OperatorNode:
            wrapper, cache = OpNode, self._op_cache
        else:
            raise TypeError(type(obj))
        if obj not in cache:
            cache[obj] = wrapper(obj)
        return cache[obj]

    def compile(self, *args):
        self._function = super().compile(_unwrap(args))
        return self

    def execute(self, *args):
        assert self._future is None
        self._future = self._executor.submit(self._function.execute, *args)

    def wait(self):
        assert self._future is not None
        self._future.exception()
        self._function.wait()
        try:
            return self._future.result()
        finally:
            self._future = None

    def __call__(self, *args):
        self.execute(*args)
        return self.wait()

    def make_const(self, data, dtype=None, device=None):
        if isinstance(data, _imperative_rt.DeviceTensorND):
            assert dtype is None and device is None
            return self._wrap(_imperative_rt.make_shared(self, data))
        else:
            data = np.asarray(data, dtype=dtype)
            if data.dtype == np.float64:
                data = data.astype(np.float32)
            elif data.dtype == np.int64:
                data = data.astype(np.int32)
            device = as_device(device).to_c()
            return self._wrap(_imperative_rt.make_const(self, data, device, dtype))

    def make_input(self, *args: "VarNode", device=None, dtype=None, shape=None):
        opnode = InputNode(*args, device=device, dtype=dtype, shape=shape, graph=self)
        return opnode.outputs[0]

    def make_h2d(self, *, dtype, device):
        device = as_device(device).to_c()
        return self._wrap(_imperative_rt.make_h2d(self, device, dtype))


def dump(*args):
    return _imperative_rt.dump_graph([i._node for i in args])


class VarNode(TensorBase):
    def __init__(self, node: _imperative_rt.VarNode):
        self._node = node
        self.graph._var_cache[node] = self

    @property
    def graph(self) -> Graph:
        return self._node.graph

    @property
    def op(self):
        return self.graph._wrap(self._node.owner)

    @property
    def name(self):
        return self._node.name

    @name.setter
    def name(self, name):
        self._node.name = name

    @property
    def dtype(self):
        return self._node.dtype

    @property
    def device(self):
        return as_device(self._node.comp_node)

    @property
    def shape(self):
        return self._node.shape

    @property
    def value(self):
        return self._node.value


class OpNode:
    def __init__(self, node: _imperative_rt.OperatorNode):
        self._node = node
        self.graph._op_cache[node] = self

    @property
    def graph(self) -> Graph:
        return self._node.graph

    @property
    def name(self):
        return self._node.name

    @name.setter
    def name(self, name):
        self._node.name = name

    @property
    def inputs(self):
        return tuple(map(self.graph._wrap, self._node.inputs))

    @property
    def outputs(self):
        return tuple(map(self.graph._wrap, self._node.outputs))


def _wrap(x):
    if isinstance(x, collections.Sequence):
        return type(x)(map(_wrap, x))
    return x.graph._wrap(x)


def _unwrap(x):
    if isinstance(x, collections.Sequence):
        return type(x)(map(_unwrap, x))
    return x._node


@apply.register()
def _(op: OpDef, *args: VarNode):
    outputs = _imperative_rt.invoke_op(op, _unwrap(args))
    return _wrap(outputs)


@apply.register()
def _(op: BackwardGraph, *args: VarNode):
    assert args
    graph = args[0].graph
    return op.interpret(lambda op, args: apply(op, *args), graph.make_const, args)


def input_callback(callback, *args, device=None, dtype=None, shape=None, graph=None):
    outputs = _imperative_rt.input_callback(
        callback, as_device(device).to_c(), dtype, shape, _unwrap(args), graph=graph
    )
    value, dummy = _wrap(outputs)
    return value, dummy


class InputNode(OpNode):
    def __init__(self, *args: VarNode, device=None, dtype=None, shape=None, graph=None):
        r = _imperative_rt.DeviceTensorNDRendezvous()
        if device is not None:
            device = as_device(device).to_c()
        outputs = _imperative_rt.input_callback(
            r, device, dtype, shape, _unwrap(args), graph=graph
        )
        super().__init__(outputs[0].owner)
        self._rendezvous = r

    def set_value(self, value):
        assert isinstance(value, _imperative_rt.DeviceTensorND)
        self._rendezvous.set(value)

    def reset(self):
        self._rendezvous.reset()

    @property
    def device(self):
        return self.outputs[0].device

    @property
    def dtype(self):
        return self.outputs[0].dtype


def output_callback(callback, var, *args):
    args = (var,) + args
    dummy = _imperative_rt.output_callback(callback, _unwrap(args))
    return _wrap(dummy)


class OutputNode(OpNode):
    def __init__(self, var, *args):
        args = (var,) + args
        r = _imperative_rt.DeviceTensorNDRendezvous()
        dummy = _imperative_rt.output_callback(r, _unwrap(args))
        super().__init__(dummy.owner)
        self._rendezvous = r

    def get_value(self):
        return self._rendezvous.get()

    def drop_value(self):
        self._rendezvous.drop()

    def reset(self):
        self._rendezvous.reset()


class ValueOutputNode(OpNode):
    def __init__(self, var, *args):
        args = (var,) + args
        r = _imperative_rt.HostTensorNDRendezvous()
        dummy = _imperative_rt.value_output_callback(r, _unwrap(args))
        super().__init__(dummy.owner)
        self._rendezvous = r

    def get_value(self):
        hostnd, event = self._rendezvous.get()
        event.wait()
        return hostnd.numpy()

    def drop_value(self):
        self._rendezvous.drop()

    def reset(self):
        self._rendezvous.reset()


class TensorAttr:
    def __init__(self, shape, dtype, device):
        self.shape = shape
        self.dtype = dtype
        self.device = device


class AttrOutputNode(OpNode):
    def __init__(self, var, *args):
        args = (var,) + args
        r = _imperative_rt.TensorAttrRendezvous()
        dummy = _imperative_rt.attr_output_callback(r, _unwrap(args))
        super().__init__(dummy.owner)
        self._rendezvous = r

    def get_value(self):
        attr = self._rendezvous.get()
        return TensorAttr(attr.shape, attr.dtype, as_device(attr.comp_node))

    def drop_value(self):
        self._rendezvous.drop()

    def reset(self):
        self._rendezvous.reset()
