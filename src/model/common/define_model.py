import torch
import torch.nn as nn
from torchvision.models import squeezenet1_1

TRUNK_END = 12


def build_squeezenet(num_classes=1000):
    return squeezenet1_1(weights=None, num_classes=num_classes)


def replace_head(net, num_classes, seed=0):
    conv = nn.Conv2d(512, num_classes, kernel_size=1)
    g = torch.Generator().manual_seed(int(seed))
    with torch.no_grad():
        conv.weight.normal_(0.0, 0.01, generator=g)
        conv.bias.zero_()
    net.classifier[1] = conv
    net.num_classes = num_classes
    return net


def split_model(net, cut=TRUNK_END):
    trunk = net.features[:cut]
    head = nn.Sequential(*net.features[cut:], net.classifier, nn.Flatten())
    return trunk, head


def count_params(module, trainable_only=False):
    return sum(p.numel() for p in module.parameters() if p.requires_grad or not trainable_only)
