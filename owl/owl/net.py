import owl
import owl.elewise as ele
import owl.conv as co
import numpy as np
import Queue
from caffe import *
from netio import ImageNetDataProvider

class ComputeUnit(object):
    def __init__(self, params):
        self.params = params
        self.name = params.name
        self.btm_names = []
        self.top_names = []
    def __str__(self):
        return 'N/A unit'
    def forward(self, from_btm, to_top):
        pass
    def backward(self, from_top, to_btm):
        pass
    def update(self):
        pass

class ComputeUnitSimple(ComputeUnit):
    def __init__(self, params):
        super(ComputeUnitSimple, self).__init__(params)
    def forward(self, from_btm, to_top):
        to_top[self.top_names[0]] = self.ff(from_btm[self.btm_names[0]])
    def ff(self, act):
        pass
    def backward(self, from_top, to_btm):
        to_btm[self.btm_names[0]] = self.bp(from_top[self.top_names[0]])
    def bp(self, sen):
        pass

class WeightedComputeUnit(ComputeUnitSimple):
    def __init__(self, params):
        super(WeightedComputeUnit, self).__init__(params)
        self.params = params
        # weights and bias
        self.weight = None
        self.weightdelta = None
        self.weightgrad = None
        self.bias = None
        self.biasdelta = None
        self.biasgrad = None
        # blob learning rate and weight decay
        self.blobs_lr = params.blobs_lr
        self.weight_decay = params.weight_decay

    def weight_update(self, base_lr, base_weight_decay, momentum, batch_size):
        #TODO: need recheck with caffe with what's the multiplier for weight decay
        if self.weightdelta == None:
            self.weightdelta = owl.zeros(self.weightgrad.shape)
        self.weightdelta = momentum * self.weightdelta - base_lr * self.blobs_lr[0] * self.weightgrad / batch_size - base_lr * self.blobs_lr[0] * base_weight_decay * self.weight_decay[0] / batch_size * self.weight
        self.weight += self.weightdelta 
        self.weightgrad = None
        
        if self.biasdelta == None:
            self.biasdelta = owl.zeros(self.biasgrad.shape)
        self.biasdelta = momentum * self.biasdelta - base_lr * self.blobs_lr[1] * self.biasgrad / batch_size - base_lr * self.blobs_lr[1] * base_weight_decay * self.weight_decay[1] / batch_size * self.bias
        self.bias += self.biasdelta 
        self.biasgrad = None



class LinearUnit(ComputeUnitSimple):
    def ff(self, x):
        return x
    def bp(self, y):
        return y
    def __str__(self):
        return 'linear'

class SigmoidUnit(ComputeUnitSimple):
    def ff(self, x):
        return ele.sigm(x)
    def bp(self, y):
        return ele.sigm_back(y)
    def __str__(self):
        return 'sigmoid'

class ReluUnit(ComputeUnitSimple):
    def ff(self, x):
        self.ff_x = x
        return ele.relu(x)
    def bp(self, y):
        return ele.relu_back(y, self.ff_x)
    def __str__(self):
        return 'relu'

class TanhUnit(ComputeUnitSimple):
    def ff(self, x):
        return ele.tanh(x)
    def bp(self, y):
        return ele.tanh_back(y)
    def __str__(self):
        return 'tanh'

class PoolingUnit(ComputeUnitSimple):
    def __init__(self, params):
        super(PoolingUnit, self).__init__(params)
        ppa = params.pooling_param
        if ppa.pool == PoolingParameter.PoolMethod.Value('MAX'):
            pool_ty = co.pool_op.max
        elif ppa.pool == PoolingParameter.PoolMethod.Value('AVE'):
            pool_ty = co.pool_op.avg
        self.pooler = co.Pooler(ppa.kernel_size, ppa.kernel_size, ppa.stride, ppa.stride, ppa.pad, ppa.pad, pool_ty)
    def ff(self, x):
        self.ff_x = x
        self.ff_y = self.pooler.ff(x)
        return self.ff_y
    def bp(self, y):
        return self.pooler.bp(y, self.ff_y, self.ff_x)
    def __str__(self):
        return 'pooling'

class DropoutUnit(ComputeUnitSimple):
    def __init__(self, params):
        super(DropoutUnit, self).__init__(params)
    def ff(self, x):
        self.dropmask = owl.randb(x.shape, self.params.dropout_param.dropout_ratio)
        return ele.mult(x, self.dropmask)
    def bp(self, y):
        return ele.mult(y, self.dropmask)
    def __str__(self):
        return 'dropout'

class SoftmaxUnit(ComputeUnit):
    def __init__(self, params):
        super(SoftmaxUnit, self).__init__(params)
    def forward(self, from_btm, to_top):
        to_top[self.top_names[0]] = co.softmax(from_btm[self.btm_names[0]], co.soft_op.instance)
        self.ff_y = to_top[self.top_names[0]]
        self.y = from_btm[self.btm_names[0]]
    def backward(self, from_top, to_btm):
        to_btm[self.btm_names[0]] = self.ff_y - self.y
    def __str__(self):
        return 'softmax'

class AccuracyUnit(ComputeUnit):
    def __init__(self, params):
        super(AccuracyUnit, self).__init__(params)
        self.acc = 0
    def forward(self, from_btm, to_top):
        predict = from_btm[self.btm_names[0]].argmax(0)
        ground_truth = from_btm[self.btm_names[1]].argmax(0)   
        minibatch_size = from_btm[self.btm_names[0]].shape[1]
        correct = (predict - ground_truth).count_zero()
        self.acc = 1 - (minibatch_size - correct) * 1.0 / minibatch_size 

    def backward(self, from_top, to_btm):
        pass
    def __str__(self):
        return 'accuracy'

class LRNUnit(ComputeUnitSimple):
    def __init__(self, params):
        super(LRNUnit, self).__init__(params)
        self.lrner = co.Lrner(params.lrn_param.local_size, params.lrn_param.alpha, params.lrn_param.beta)
        self.scale = None
    def ff(self, x):
        self.ff_x = x
        self.scale = owl.zeros(x.shape)
        self.ff_y = self.lrner.ff(x, self.scale)
        return self.ff_y
    def bp(self, y):
        return self.lrner.bp(self.ff_x, self.ff_y, self.scale, y)
    def __str__(self):
        return 'lrn'

class ConcatUnit(ComputeUnit):
    def __init__(self, params):
        super(ConcatUnit, self).__init__(params)
        self.concat_dim_caffe = params.concat_param.concat_dim
        self.slice_count = []
    def forward(self, from_btm, to_top):
        narrays = []
        self.concat_dim = len(from_btm[self.btm_names[0]].shape) - 1 - self.concat_dim_caffe
        for i in range(len(self.btm_names)):
            narrays.append(from_btm[self.btm_names[i]])
            self.slice_count.append(from_btm[self.btm_names[i]].shape[self.concat_dim])
        #caffe concat_dim is reversed
        to_top[self.top_names[0]] = owl.concat(narrays, self.concat_dim)
    def backward(self, from_top, to_btm):
        st_off = 0
        for i in range(len(self.btm_names)):
            to_btm[self.btm_names[i]]  = owl.slice(from_top[self.top_names[0]], self.concat_dim, st_off, self.slice_count[i])
            st_off += self.slice_count[i]
    def __str__(self):
        return 'concat'

class FullyConnection(WeightedComputeUnit):
    def __init__(self, params):
        super(FullyConnection, self).__init__(params)
        self.inner_product_param = params.inner_product_param
        
    def ff(self, act):
        shp = act.shape
        if len(shp) > 2:
            a = act.reshape([np.prod(shp[0:-1]), shp[-1]])
        else:
            a = act
        self.ff_act = act # save ff value
        return self.weight * a + self.bias
    def bp(self, sen):
        shp = self.ff_act.shape
        if len(shp) > 2:
            a = self.ff_act.reshape([np.prod(shp[0:-1]), shp[-1]])
        else:
            a = self.ff_act
        self.weightgrad = sen * a.trans()
        self.biasgrad = sen.sum(1)
        s = self.weight.trans() * sen 
        if len(shp) > 2:
            s = s.reshape(shp)
        return s
    def __str__(self):
        return 'fc'

class ConvConnection(WeightedComputeUnit):
    def __init__(self, params):
        super(ConvConnection, self).__init__(params)
        self.conv_params = params.convolution_param
        self.convolver = co.Convolver(self.conv_params.pad, 
                self.conv_params.pad, self.conv_params.stride, self.conv_params.stride)
        self.convolution_param = params.convolution_param
        self.num_output = params.convolution_param.num_output
    def ff(self, act):
        self.ff_act = act
        return self.convolver.ff(act, self.weight, self.bias)
    def bp(self, sen):
        self.weightgrad = self.convolver.weight_grad(sen, self.ff_act, self.weight)
        self.biasgrad = self.convolver.bias_grad(sen)
        return self.convolver.bp(sen, self.ff_act, self.weight)
    def __str__(self):
        return 'conv'

class DataUnit(ComputeUnit):
    def __init__(self, params):
        super(DataUnit, self).__init__(params)
        self.crop_size = params.transform_param.crop_size
        #TODO: set num_channel to 3, it's a hack
        self.num_output = 3
        self.dp = ImageNetDataProvider(params.transform_param.mean_file, params.data_param.source, params.data_param.batch_size, params.transform_param.crop_size)
        self.generator = self.dp.get_train_mb()
        #return ImageNetDataProvider(params.transform_param.mean_file, params.data_param.source, params.data_param.batch_size, params.transform_param.crop_size)

    def forward(self, from_btm, to_top):
        samples, labels = next(self.generator) 
        to_top[self.top_names[0]] = owl.from_numpy(samples).reshape([self.crop_size, self.crop_size, 3, samples.shape[0]])
        to_top[self.top_names[1]] = owl.from_numpy(labels)
    def backward(self, from_top, to_btm):
        pass
    def __str__(self):
        return 'data'

class Net:
    def __init__(self):
        self.units = []
        self.adjacent = []
        self.reverse_adjacent = []
        self.base_lr = 0
        self.base_weight_decay = 0
        self.momentum = 0
        self.name_to_uid = {}
        #self.dataprovider = []
        #self.dname_to_dpid = {}

    def add_unit(self, unit):
        uid = len(self.units)
        self.units.append(unit)
        self.adjacent.append([])
        self.reverse_adjacent.append([])
        if not unit.name in self.name_to_uid:
            self.name_to_uid[unit.name] = []
        self.name_to_uid[unit.name].append(uid)
        return uid

    def connect(self, u1, u2):
        self.adjacent[u1].append(u2)
        self.reverse_adjacent[u2].append(u1)

    def _is_excluded(self, unit, phase):
        p = self.units[unit].params
        return phase != None and len(p.include) != 0 and p.include[0].phase != Phase.Value(phase)

    def _toporder(self, phase = None):
        depcount = [len(inunits) for inunits in self.reverse_adjacent]
        queue = Queue.Queue()
        # remove dep from excluded units
        for unit in range(len(depcount)):
            if self._is_excluded(unit, phase):
                for l in self.adjacent[unit]:
                    depcount[l] -= 1
        # find start units
        for unit in range(len(depcount)):
            count = depcount[unit]
            if count == 0:
                queue.put(unit)
        # run
        while not queue.empty():
            unit = queue.get()
            if self._is_excluded(unit, phase):
                continue
            yield unit
            for l in self.adjacent[unit]:
                depcount[l] -= 1
                if depcount[l] == 0:
                    queue.put(l)

    def _reverse_toporder(self, phase = None):
        depcount = [len(outunits) for outunits in self.adjacent]
        queue = Queue.Queue()
        # remove dep from excluded units
        for unit in range(len(depcount)):
            if self._is_excluded(unit, phase):
                for l in self.reverse_adjacent[unit]:
                    depcount[l] -= 1
        # find start units
        for unit in range(len(depcount)):
            count = depcount[unit]
            if count == 0:
                queue.put(unit)
        # run
        while not queue.empty():
            unit = queue.get()
            if self._is_excluded(unit, phase):
                continue
            yield unit
            for l in self.reverse_adjacent[unit]:
                depcount[l] -= 1
                if depcount[l] == 0:
                    queue.put(l)

    def forward(self, phase = 'TRAIN'):
        print "begin forward =============================="
        unit_to_tops = [{} for name in self.units]
        for u in self._toporder(phase):
            from_btm = {}
            for btm in self.reverse_adjacent[u]:
                from_btm.update(unit_to_tops[btm])
            #print self.units[u].name
            self.units[u].forward(from_btm, unit_to_tops[u])

    def backward(self, phase = 'TRAIN'):
        print "begin backward ============================"
        unit_to_btms = [{} for name in self.units]
        for u in self._reverse_toporder(phase):
            from_top = {}
            for top in self.adjacent[u]:
                from_top.update(unit_to_btms[top])
            #print self.units[u].name
            self.units[u].backward(from_top, unit_to_btms[u])
    
    def weight_update(self):
        for i in range(len(self.units)):
            if isinstance(self.units[i], WeightedComputeUnit):
                self.units[i].weight_update(self.base_lr, self.base_weight_decay, self.momentum, self.batch_size)

    def __str__(self):
        ret = 'digraph G {\n'
        for uid in range(len(self.units)):
            ret += 'n' + str(uid) + ' [label="' + self.units[uid].name + '"]\n'
        for uid in range(len(self.units)):
            for nuid in self.adjacent[uid]:
                ret += 'n' + str(uid) + ' -> n' + str(nuid) + '\n'
        return ret + '}\n'


############### Test code
class _StartUnit(ComputeUnit):
    def __init__(self, name):
        self.name = name
        self.btm_names = []
        self.top_names = []
    def forward(self, from_btm, to_top):
        print 'ff|start name:', self.name
        to_top[self.top_names[0]] = 0
    def backward(self, from_top, to_btm):
        pass

class _EndUnit(ComputeUnit):
    def __init__(self, name):
        self.name = name
        self.btm_names = []
        self.top_names = []
    def forward(self, from_btm, to_top):
        pass
    def backward(self, from_top, to_btm):
        print 'bp|end name:', self.name
        to_btm[self.btm_names[0]] = 0

class _TestUnit(ComputeUnitSimple):
    def __init__(self, name):
        self.name = name
        self.btm_names = []
        self.top_names = []
    def ff(self, x):
        print 'ff|name:', self.name, 'val:', x
        return x + 1
    def bp(self, y):
        print 'bp|name:', self.name, 'val:', y
        return y - 1

if __name__ == '__main__':
    net = Net()
    us = _StartUnit('s')
    u1 = _TestUnit('u1')
    u2 = _TestUnit('u2')
    u3 = _TestUnit('u3')
    u4 = _TestUnit('u4')
    u5 = _TestUnit('u5')
    ue = _EndUnit('e')
    us.top_names = ['s']
    u1.btm_names = ['s']
    u1.top_names = ['u1']
    u2.btm_names = ['u1']
    u2.top_names = ['u2']
    u3.btm_names = ['u2']
    u3.top_names = ['u3']
    u4.btm_names = ['u3']
    u4.top_names = ['u4']
    u5.btm_names = ['u4']
    u5.top_names = ['u5']
    ue.btm_names = ['u5']
    ls = net.add_unit(us)
    l1 = net.add_unit(u1)
    l2 = net.add_unit(u2)
    l3 = net.add_unit(u3)
    l4 = net.add_unit(u4)
    l5 = net.add_unit(u5)
    le = net.add_unit(ue)
    net.connect(ls, l1)
    net.connect(l1, l2)
    net.connect(l2, l3)
    net.connect(l3, l4)
    net.connect(l4, l5)
    net.connect(l5, le)
    net.forward()
    net.backward()
