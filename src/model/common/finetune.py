import torch
from torchvision.models import squeezenet1_1, SqueezeNet1_1_Weights

from . import define_model as dm
from .paths import ROOT

TRAINABLE_PREFIXES = {
    'classifier': ['classifier'],
    'fire9_classifier': ['features.12', 'classifier'],
    'fire8_fire9_classifier': ['features.11', 'features.12', 'classifier'],
    'all': None,
}


def feature_cut(mode):
    return 13 if mode == 'classifier' else dm.TRUNK_END


def load_imagenet_weights(net, cfg):
    path = ROOT / cfg['model']['pretrained_path']
    if path.exists():
        net.load_state_dict(torch.load(path, map_location='cpu'))
        return str(path)
    if cfg['model'].get('pretrained_source') == 'torchvision':
        ref = squeezenet1_1(weights=SqueezeNet1_1_Weights.IMAGENET1K_V1)
        net.load_state_dict(ref.state_dict())
        return 'torchvision:IMAGENET1K_V1'
    raise FileNotFoundError(f'không thấy trọng số ImageNet: {path}')


def set_trainable(net, mode):
    if mode not in TRAINABLE_PREFIXES:
        raise ValueError(f'trainable phải thuộc {list(TRAINABLE_PREFIXES)}, nhận {mode}')
    prefixes = TRAINABLE_PREFIXES[mode]
    for name, p in net.named_parameters():
        p.requires_grad = prefixes is None or any(name.startswith(pre + '.') for pre in prefixes)
    return net


def prepare_model(cfg, pretrained=True):
    net = dm.build_squeezenet(1000)
    source = load_imagenet_weights(net, cfg) if pretrained else 'khong_nap'
    dm.replace_head(net, len(cfg['classes']), cfg['seed'])
    set_trainable(net, cfg['model']['trainable'])
    return net, source


def trainable_vector(net):
    return torch.cat([p.detach().flatten() for p in net.parameters() if p.requires_grad]).numpy()


def summary(net):
    layers = {}
    for name, p in net.named_parameters():
        key = '.'.join(name.split('.')[:2]) if name.startswith('features') else name.split('.')[0]
        item = layers.setdefault(key, {'params': 0, 'trainable': p.requires_grad})
        item['params'] += p.numel()
    return {
        'tong': dm.count_params(net),
        'huan_luyen': dm.count_params(net, trainable_only=True),
        'dong_bang': dm.count_params(net) - dm.count_params(net, trainable_only=True),
        'theo_lop': layers,
    }
