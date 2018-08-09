#PixelCNN:
import time
import os
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim import lr_scheduler
import torchvision
from torchvision import datasets, transforms, utils
from pixelcnn.utils import * 
from pixelcnn.model import * 
from PIL import Image


#VHE:
from builtins import super
import random

import torch
from torch import nn, optim
from torch.distributions.normal import Normal
import math

from vhe import VHE, DataLoader, Factors, Result, NormalPrior, Transform

#######pixelcnn options #########
parser = argparse.ArgumentParser()
# data I/O
parser.add_argument('-i', '--data_dir', type=str,
                    default='data', help='Location for the dataset')
parser.add_argument('-d', '--dataset', type=str,
                    default='omni', help='Can be either cifar|mnist|omni')
# model
parser.add_argument('-q', '--nr_resnet', type=int, default=4,
                    help='Number of residual blocks per stage of the model')
parser.add_argument('-n', '--nr_filters', type=int, default=40,
                    help='Number of filters to use across the model. Higher = larger model.')
parser.add_argument('-a', '--mode', type=str, default='softmax', choices=['logistic_mix', 'softmax', 'gaussian'])
parser.add_argument('-m', '--nr_logistic_mix', type=int, default=None,
                    help='Number of logistic components in the mixture. Higher = more flexible model')
parser.add_argument('-sm', '--nr_softmax_bins', type=int, default=2,
                    help='Number of softmax bins (use instead of nr_logistic_mix)')
parser.add_argument('-l', '--lr', type=float,
                    default=0.0002, help='Base learning rate')
parser.add_argument('-e', '--lr_decay', type=float, default=0.999995,
                    help='Learning rate decay, applied every step of the optimization')
parser.add_argument('-b', '--batch_size', type=int, default=32,
                    help='Batch size during training per GPU')
parser.add_argument('-x', '--max_epochs', type=int,
                    default=400, help='How many epochs to run in total?')
parser.add_argument('-s', '--seed', type=int, default=1,
                    help='Random seed to use')
parser.add_argument('-an', '--anneal', type=int, default=None,
                    help='number of epochs to anneal')
parser.add_argument('--debug', action='store_true',
                    help='if the number of batches is small')
parser.add_argument('--ortho', dest='ortho_transforms', action='store_true')
parser.add_argument('--affine', action='store_true')

args = parser.parse_args()

if args.nr_logistic_mix is None and args.nr_softmax_bins is None:
	args.nr_logistic_mix = 10




# reproducibility
torch.manual_seed(args.seed)
np.random.seed(args.seed)

sample_batch_size = args.batch_size
obs = (1, 28, 28) 
input_channels = obs[0]
rescaling     = lambda x : (x - .5) * 2.
flip = lambda x : - x
kwargs = {'num_workers':1, 'pin_memory':True, 'drop_last':True}
resizing = lambda x: x.resize((28,28))
omni_transforms = transforms.Compose([resizing, transforms.ToTensor(), rescaling, flip])




train_loader = torch.utils.data.DataLoader(datasets.Omniglot(args.data_dir, download=True, 
                    background=True, transform=omni_transforms), batch_size=1, 
                        shuffle=True, **kwargs)

test_loader = torch.utils.data.DataLoader(datasets.Omniglot(args.data_dir, download=True, 
                    background=False, transform=omni_transforms), batch_size=1, 
                        shuffle=True, **kwargs)

if args.mode=="logistic_mix":
    loss_op   = lambda real, fake : discretized_mix_logistic_loss_1d(real, fake)
    sample_op = lambda x : sample_from_discretized_mix_logistic_1d(x, args.nr_logistic_mix)
elif args.mode=="softmax":
    loss_op   = lambda real, fake : softmax_loss_1d(real, fake)
    sample_op = lambda x : sample_from_softmax_1d(x)
elif args.mode == "gaussian":
    loss_op   = lambda real, fake: gaussian_loss(real, fake)
    sample_op = lambda x: sample_from_gaussian(x)

#######end pixelcnn options #########




x_dim = 5
c_dim = 10 
h_dim = 10


class Px(nn.Module):
	def __init__(self):
		super().__init__()

		# Regressor for the 3 * 2 affine matrix
		self.fc_loc = nn.Sequential(
			nn.Linear(10 * 3 * 3, 32),
			nn.ReLU(True),
			nn.Linear(32, 3 * 2)
			)
		# Initialize the weights/bias with identity transformation
		self.fc_loc[2].weight.data.zero_()
		self.fc_loc[2].bias.data.copy_(torch.tensor([1, 0, 0, 0, 1, 0], dtype=torch.float))		

		self.obs = (1, 28, 28)


		self.kernel=5
		self.pad = nn.ZeroPad2d((self.kernel - 1, 0, self.kernel - 1, 0))
		self.cond_conv_1 = nn.Conv2d(c_dim, args.nr_filters * 2, self.kernel, stride=1, padding=0)
		self.cond_conv_2 = nn.Conv2d(args.nr_filters * 2, args.nr_filters * 2, self.kernel, stride=2, padding=0)
		self.cond_conv_3 = nn.Conv2d(args.nr_filters * 2, args.nr_filters * 2, self.kernel, stride=2, padding=0)
		
		self.model = PixelCNN(nr_resnet=args.nr_resnet, nr_filters=args.nr_filters, 
			input_channels=input_channels,
			nr_softmax_bins=args.nr_softmax_bins, mode="softmax")
		assert args.mode == "softmax"


	def loss_op(self, real,fake): return softmax_loss_1d(real, fake)
	def sample_op(self, x): return sample_from_softmax_1d(x)

	def sample(self, model, cond_blocks=None):
		assert cond_blocks is not None
		model.train(False)
		data = torch.zeros(sample_batch_size, self.obs[0], self.obs[1], self.obs[2])
		data = data.cuda()
		for i in range(self.obs[1]):
			for j in range(self.obs[2]):
				data_v = Variable(data, volatile=True)
				out   = model(data_v, sample=True, cond_blocks=cond_blocks)
				out_sample = self.sample_op(out)
				data[:, :, i, j] = out_sample.data[:, :, i, j]
		return data, out 


	def stn(self, z, c):
		zs = z.view(-1, 10 * 3 * 3)
		theta = self.fc_loc(zs)
		theta = theta.view(-1, 2, 3)
		grid = F.affine_grid(theta, c.size())
		cond = F.grid_sample(c, grid)
		return cond

	def forward(self, c, z, x=None):
		cond = self.stn(z,c)

		cond_blocks = {}
		cond_blocks[(28, 28)] = self.cond_conv_1(self.pad(cond))
		cond_blocks[(14, 14)] = self.cond_conv_2(self.pad(cond_blocks[(28, 28)]))
		cond_blocks[(7, 7)] = self.cond_conv_3(self.pad(cond_blocks[(14, 14)]))
				

		if x is None: 

			x, dist = self.sample(self.model, cond_blocks=cond_blocks)
			return Result(x, -self.loss_op(x, dist))
		else:

			return Result(x, -self.loss_op(x, self.model(x, cond_blocks=cond_blocks, sample=False)))

class Qc_stn(nn.Module):
	def __init__(self):
		super(Qc_stn, self).__init__()
		self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
		self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
		self.conv2_drop = nn.Dropout2d()
		self.fc1 = nn.Linear(320, 50)
		self.fc2 = nn.Linear(50, 10)

		# Spatial transformer localization-network
		self.localization = nn.Sequential(
			nn.Conv2d(1, 8, kernel_size=7),
			nn.MaxPool2d(2, stride=2),
			nn.ReLU(True),
			nn.Conv2d(8, 10, kernel_size=5),
			nn.MaxPool2d(2, stride=2),
			nn.ReLU(True)
		)

		# Regressor for the 3 * 2 affine matrix
		self.fc_loc = nn.Sequential(
			nn.Linear(10 * 3 * 3, 32),
			nn.ReLU(True),
			nn.Linear(32, 3 * 2)
		)

		# Initialize the weights/bias with identity transformation
		self.fc_loc[2].weight.data.zero_()
		self.fc_loc[2].bias.data.copy_(torch.tensor([1, 0, 0, 0, 1, 0], dtype=torch.float))

		self.kernel = 5
		self.c_dim = 10
		self.pad = nn.ZeroPad2d((self.kernel - 1, 0, self.kernel - 1, 0))
		self.conv_post_stn = nn.Sequential(self.pad, nn.Conv2d(1, c_dim, self.kernel, stride=1, padding=0), nn.ReLU())
		self.conv_mu = nn.Sequential(self.pad, nn.Conv2d(c_dim, c_dim, self.kernel, stride=1, padding=0))
		self.conv_sigma = nn.Sequential(self.pad, nn.Conv2d(c_dim, c_dim, self.kernel, stride=1, padding=0), nn.Softplus())

	# Spatial transformer network forward function
	def stn(self, x):
		xs = self.localization(x)
		xs = xs.view(-1, 10 * 3 * 3)
		theta = self.fc_loc(xs)
		theta = theta.view(-1, 2, 3)
		grid = F.affine_grid(theta, x.size())
		x = F.grid_sample(x, grid)
		return x

	def forward(self, inputs, c=None):
		# transform the input
		xs = [self.stn(inputs[:,i,:,:,:]) for i in range(inputs.size(1))]

		embs = [self.conv_post_stn(x) for x in xs]
		emb = sum(embs)/len(embs)
		mu = self.conv_mu(emb)
		sigma = self.conv_sigma(emb)
		dist = Normal(mu, sigma)
		if c is None: c = dist.rsample()
		return Result(c, dist.log_prob(c).sum(dim=1).sum(dim=1).sum(dim=1))


class Qz(nn.Module):
	def __init__(self):
		super(Qz,self).__init__()
		
		
		self.localization_mu = nn.Sequential(
				nn.Conv2d(1, 8, kernel_size=7, stride=1),
				nn.MaxPool2d(2, stride=2),
				nn.ReLU(True),
				nn.Conv2d(8, 10, kernel_size=5, stride=1),
				nn.MaxPool2d(2, stride=2),
				)

		self.localization_sigma = nn.Sequential(
				nn.Conv2d(1, 8, kernel_size=7, stride=1),
				nn.MaxPool2d(2, stride=2),
				nn.ReLU(True),
				nn.Conv2d(8, 10, kernel_size=5, stride=1),
				nn.MaxPool2d(2, stride=2),
				nn.Softmax()
				)

	def forward(self, inputs, c, z=None):
		inputs = inputs.view(-1, 1, 28, 28) #huh?
		mu = self.localization_mu(inputs)
		sigma = self.localization_sigma(inputs)
		dist = Normal(mu, sigma)
		if z is None: 
			z = dist.rsample()
		score = dist.log_prob(z).sum(dim=1).sum(dim=1).sum(dim=1)
		return Result(z, score) 

class Pc(nn.Module):
	def __init__(self):
		super(Pc,self).__init__()

		self.model = PixelCNN(nr_resnet=int(args.nr_resnet/2), nr_filters=int(args.nr_filters/2), 
			input_channels=10, mode="gaussian")


		self.obs = (10, 28, 28) if 'mnist' in args.dataset or 'omni' in args.dataset else (3, 32, 32)

	def loss_op(self, real,fake): return gaussian_loss(real, fake)
	def sample_op(self, x): return sample_from_gaussian(x)

	def sample(self,model): 
		assert latents is not None
		model.train(False)
		data = torch.zeros(sample_batch_size, self.obs[0], self.obs[1], self.obs[2]) #TODO: fix sample batch size
		data = data.cuda()
		for i in range(self.obs[1]):
			for j in range(self.obs[2]):
				data_v = Variable(data, volatile=True)
				out   = model(data_v, sample=True)
				out_sample = self.sample_op(out)
				data[:, :, i, j] = out_sample.data[:, :, i, j]
		return data, out


	def forward(self, c=None):
		if c is None: 
			c, dist = self.sample(self.model)
			return Result(c, -self.loss_op(c, dist))
		else:
			return Result(c, -self.loss_op(c, self.model(c, sample=False)))


if __name__ == '__main__':

	prior = Factors(c=Pc(), z=NormalPrior())
	encoder = Factors(c=Qc_stn(), z=Qz())
	decoder = Px()
	vhe = VHE(encoder, decoder, prior=prior)
	vhe = vhe.cuda()
	print("created vhe")
	print("number of parameters is", sum(p.numel() for p in vhe.parameters() if p.requires_grad))

	# TODO:
	# reloadmodel = False
	# if reloadmodel:
	# 	vhe.load_state_dict(torch.load('VHE_pixelCNN_epoch_5.p'))

	########## Generate dataset############
	from itertools import islice

	if args.debug:
		data_cutoff = 50
		data, class_labels = zip(*islice(train_loader, data_cutoff))
	else:
		data_cutoff = None
		data, class_labels = zip(*train_loader)

	data = torch.cat(data)


	batch_size = args.batch_size
	n_inputs = 2


	ortho_grids = []
	for flip in [1,-1]:
		for theta in [0, math.pi/2, math.pi, 3*math.pi/2]:

			trans = torch.Tensor([[math.cos(theta), flip*-math.sin(theta), 0], [math.sin(theta), flip*math.cos(theta), 0]]).view(1,2,3)
			trans = trans.repeat(1,1,1) #??
			grid = F.affine_grid(trans,torch.Size([1,1,28,28]))
			ortho_grids.append( grid ) 

	ortho_grids = torch.cat(ortho_grids,0)



	small_grids = []
	for _ in range(20):
		
		trans = torch.Tensor([[1,0,0],[0,1,0] ]).view(1,2,3) #+ torch.randn(1,2,3)*0.05
		trans = trans.repeat(1,1,1)
		grid = F.affine_grid(trans, torch.Size([1,1,28,28]))
		small_grids.append( grid ) 
	small_grids = torch.cat(small_grids,0)




	transform_small_affine = Transform(F.grid_sample, small_grids, share_labels=['c'])
	transform_ortho_affine = Transform(F.grid_sample, ortho_grids, share_labels=None)

	data_loader = DataLoader(data=data, labels = {'c':class_labels, 'z':range(len(data))},
			batch_size=batch_size, k_shot= {'c': n_inputs, 'z': 1}, transforms=[transform_small_affine]) #, transform_ortho_affine])

	#training data:
	if data_cutoff is not None:
		test_data, test_class_labels = zip(*islice(test_loader, data_cutoff))
	else:
		test_data, test_class_labels = zip(*test_loader)
	test_data = torch.cat(test_data)
	print("test dataset size", test_data.size())

	test_data_loader = DataLoader(data=test_data, labels = {'c':test_class_labels, 'z':range(len(test_data))},
			batch_size=batch_size, k_shot= {'c': n_inputs, 'z': 1})


	###sample 20 random affine transforms
	if args.affine:
		id_trans = torch.Tensor([[1, 0, 0], [0, 1, 0]]).view(1,2,3)
		id_trans = id_trans.repeat(data.size(0),1,1)
	############batch


	# Training
	print("started training")

	optimiser = optim.Adam(vhe.parameters(), lr=1e-3)
	scheduler = lr_scheduler.StepLR(optimiser, step_size=1, gamma=args.lr_decay)

	total_iter = 0
	for epoch in range(1, args.max_epochs):

		kl_factor = min((epoch-1)/args.anneal, 1) if args.anneal else 1
		
		print("kl_factor:", kl_factor)
		batchnum = 0
		for batch in data_loader:
			inputs = {k:v.cuda() for k,v in batch.inputs.items()}
			sizes = batch.sizes
			target = batch.target.cuda()

			optimiser.zero_grad()
			score, kl = vhe.score(inputs=inputs, sizes=sizes, x=target, return_kl=True, kl_factor=kl_factor)
			(-score).backward() 
			optimiser.step()
			batchnum += 1
			print("Batch %d Score %3.3f KLc %3.3f KLz %3.3f" % (batchnum, score.item(), kl.c.item(), kl.z.item()),flush=True)
			total_iter = total_iter + 1
		print("---Epoch %d Score %3.3f KLc %3.3f KLz %3.3f" % (epoch, score.item(), kl.c.item(), kl.z.item()))

		if epoch %5==0: 
			torch.save(vhe.state_dict(), './VHE_pixelCNN_epoch_{}.p'.format(epoch))
			print("saved model")


			#Sampling:
			for batch in islice(test_data_loader, 1):
				test_inputs = {k:v.cuda() for k,v in batch.inputs.items()}
				print("\nPosterior predictive for test inputs")
				sampled_x = vhe.sample(inputs={'c':test_inputs['c']}).x 


			torchvision.utils.save_image([test_inputs['c'][i,j,:,:,:] for j in range(n_inputs) for i in range(args.batch_size)] , "sample_support_epoch_{}.png".format(epoch), padding=5, pad_value=1, nrow=args.batch_size)
			torchvision.utils.save_image(sampled_x, "samples_epoch_{}.png".format(epoch), padding=5, pad_value=1, nrow=args.batch_size)


		#do testing
		vhe.train()

		#may not want this, but can keep:
		scheduler.step()


