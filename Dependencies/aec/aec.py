import ctypes
import numpy as np
import os

# Load the shared library
LIB_PATH = "webrtc-audio-processing/libwebrtc_wrapper.so"
lib = ctypes.cdll.LoadLibrary(LIB_PATH)

# Initialize the APM processor
lib.init_apm()

# Define the interface to your functions
def aec_process(mic_frame: np.ndarray, far_frame: np.ndarray, sample_rate=16000) -> np.ndarray:
	assert mic_frame.shape == far_frame.shape
	assert mic_frame.dtype == np.int16 and far_frame.dtype == np.int16
	
	mic = mic_frame.copy()
	far = far_frame.copy()
	
	mic_ptr = mic.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
	far_ptr = far.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
	
	# First process the far-end (playback) signal
	lib.process_reverse_stream(far_ptr, len(far), sample_rate)
	
	# Then process the mic (near-end) signal
	lib.process_stream(mic_ptr, len(mic), sample_rate)
	
	return mic
