#!/usr/bin/env python3
# Harmonic-mean Multi-label Classifier
# The model uses harmonic-mean of distance to training samples to classify, does not require training

import os, sys
import numpy as np

class Model:
	fn_extension = '.pson'
	delta = 1e-5
	def __init__(self, name, n_save=10) -> None:
		"""Create a Harmonic-mean Multi-label Classifier Model and auto-load from file if present

		Args:
			name (_type_): model_name, the model filename will be `model_name.pson`
			n_save (int, optional): the max number of data points to store for each class. Defaults to 10.
		"""
		self.filename = name + self.fn_extension
		self.n_save = n_save
		if os.path.isfile(self.filename):
			self.data = eval(open(self.filename).read())
		else:
			self.data = {}

	def save(self):
		with open(self.filename, 'w') as fp:
			fp.write(str(self.data))

	def add(self, x, y, save=True):
		lst = self.data.get(y, [])
		self.data[y] = (lst+[x])[:self.n_save]
		if save:
			self.save()

	def HMD(self, x, arr):
		"""Compute the Harmonic-mean-distance between x and every value of arr

		Args:
			x (_type_): input value
			arr (_type_): input array

		Returns:
			float: Harmonic-mean-distance value
		"""
		return 1/np.mean(1/(abs(np.array(arr)-x)+self.delta))

	def predict(self, x):
		dists = [[cls, self.HDM(x,arr)] for cls, arr in self.data.items()]
		cls = sorted(dists, key=lambda t:t[1])[0][0]
		return cls
