import torch
from torch._C import device
from torch.nn.modules.module import _forward_unimplemented
from torch.optim import SGD
from copy import deepcopy
from torch import nn

def save_tracin_checkpoint(model, epoch, loss, optimizer, path):
    """Saves a checkpoint for tracin to a path

    Args:
        model ([type]): [description]
        epoch ([type]): [description]
        loss ([type]): [description]
        optimizer ([type]): [description]
        path ([type]): [description]
    """
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'loss': loss
    }, path)
    return

def load_tracin_checkpoint(model, optimizer, path):
    """Loads a tracin checkpoint from a path

    Args:
        model ([type]): [description]
        optimizer ([type]): [description]
        path ([type]): [description]

    Returns:
        [type]: [description]
    """
    checkpoint = torch.load(path)
    model.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    epoch = checkpoint['epoch']
    loss = checkpoint['loss']
    return model, optimizer, epoch, loss

def calculate_tracin_influence(model, source, source_label, target, target_label, optimizer, paths, device):
    """Calculates influence of source on target datapoint based on TracIn method from checkpoints

    Args:
        model ([type]): [description]
        source ([type]): [description]
        target ([type]): [description]
        optimizer ([type]): [description]
        criterion ([type]): [description]
        paths ([type]): [description]
    """
    if optimizer != "SGD":
        raise Exception("Wrong optimizer, can only use SGD")
    num_checkpoints = len(paths)
    influence = 0
    # print("Source ", source)
    # curr_model = model(input_size=128, output_size=5673, hidden_dim=64, n_layers=1) 
    # curr_model.LSTM.flatten_parameters()
    # optimizer = SGD(curr_model.parameters(), lr=5e-2, momentum=0.9)
    curr_model = model(input_size=128, output_size=5673, hidden_dim=64, n_layers=1, device=device)
    curr_model.LSTM.flatten_parameters()
    for model_index in range(num_checkpoints):
        # print("in it")
        influence += helper_influence(curr_model, source.detach().clone(), source_label.detach().clone(), target.detach().clone(), target_label.detach().clone(), paths[model_index], device)
        # print("Path: ", paths[model_index] )
        # print("Influence: ", influence)
    return influence

def helper_influence(curr_model, source, source_label, target, target_label, path, device):
    optimizer = SGD(curr_model.parameters(), lr=5e-2, momentum=0.9)
    curr_model, model_optimizer, _, _ = load_tracin_checkpoint(curr_model,optimizer, path)
    lr = get_lr(model_optimizer)
    source = curr_model.item_emb(torch.LongTensor(source))
    target = curr_model.item_emb(torch.LongTensor(target))
    source = torch.stack([source], dim=0).to(device)
    target = torch.stack([target], dim=0).to(device)
    source_label.to(device)
    target_label.to(device)
    curr_model.to(device)
    print("source \n", source, source.get_device())
    print("target \n", target, target.get_device())
    print("source label is \n", source_label, source_label.get_device())
    print("target_label is \n", target_label, target_label.get_device())
    print("model is \n", curr_model, next(curr_model.parameters()).is_cuda)
    # print("LR is ", lr)
    # Get source gradients 
    model_optimizer.zero_grad()
    criterion = nn.CrossEntropyLoss()
    source_outputs, _ = curr_model.forward(source)
    # print("Source outputs are ", source_outputs, source_outputs[0].shape)
    # print("first element", source_outputs[0])
    # print("Source label is ", source_label)
    source_loss = criterion(source_outputs[0:1], source_label)
    # print("source loss is ", source_loss)
    source_loss.backward()
    source_gradients = curr_model.get_gradients(device)
    # Get target gradients
    model_optimizer.zero_grad()
    # print("target outputs are ", target_outputs)
    criterion(curr_model.forward(target)[0][0:1], target_label).backward()
    # print("target loss is ", target_loss)
    target_gradients = curr_model.get_gradients(device)
    # Calculate influence for this epoch. Flatten weights and dot product.
    val = torch.dot(source_gradients, target_gradients)
    val += val * lr
    return val

def get_lr(optimizer):
    """Gets learning rate given an optimizer

    Args:
        optimizer ([type]): [description]
    """
    for param_group in optimizer.param_groups:
        return param_group['lr']


def run_experiments(model, sources, sources_labels, targets, targets_labels, paths, device, optimizer="SGD"):
    # Loop through all source target combinations
    influences = []
    print("Device is ", device)
    for source, source_label in zip(sources, sources_labels):
        for target, target_label in zip(targets, targets_labels):
            source = torch.LongTensor(source)
            source_label = torch.LongTensor([source_label]).to(device)
            target = torch.LongTensor(target)
            target_label = torch.LongTensor([target_label]).to(device)
            single_influence = calculate_tracin_influence(model, source, source_label, target, target_label, optimizer, paths, device)
            influences.append(single_influence)
    return influences


if __name__ == "__main__":
    print("This doesn't do jack")