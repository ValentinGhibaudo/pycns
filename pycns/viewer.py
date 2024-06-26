# https://ipywidgets.readthedocs.io/en/7.6.3/examples/Widget%20Styling.html


import datetime

import numpy as np

import xarray as xr

import matplotlib.pyplot as plt

import ipywidgets.widgets as W
import traitlets

from .reader import CnsReader

import time

# TODO expandable layout for fiigure.canvas

class DataFromXarray:
    def __init__(self, ds):
        self.ds = ds
        self.prefered_dtype = np.dtype('datetime64[ns]')
        self.events = None

    def get_stream_names(self):
        return list(self.ds.keys())

    def get_start_stop(self, stream_names):
        if 'times' in self.ds.coords:
            # resample times
            start = self.ds['times'].values[0]
            stop = self.ds['times'].values[-1]
        else:
            # one time vector per stream
            start = min([self.ds[f'times_{name}'].values[0] for name in stream_names])
            stop = max([self.ds[f'times_{name}'].values[-1] for name in stream_names])
        return start, stop
    
    def get_channels(self, stream_names):
        channels =[]
        for stream_name in self.ds.keys():
            if stream_names is not None and stream_name not in stream_names:
                continue
            arr = self.ds[stream_name]
            if arr.ndim == 1:
                channels.append(stream_name)
            elif self.ds[stream_name].ndim == 2:
                chan_coords = [k for k in arr.coords.keys() if not k.startswith('times')][0]
                chans = list(arr.coords[chan_coords].values)
                channels.extend([f'{stream_name}/{chan}' for chan in chans])
        return channels
    
    def get_units(self, stream_name):
        if 'units' in self.ds[stream_name].attrs:
            return self.ds[stream_name].attrs['units']

    def get_signal(self, stream_name, chan, t0, t1):
        arr = self.ds[stream_name]
        # the times is the first coords always
        time_coords = arr.dims[0]
        d = {time_coords: slice(t0, t1)}
        arr = arr.sel(**d)
        if chan is not None:
            #EEG channel slice
            chan_coords = [k for k in arr.coords.keys() if not k.startswith('times_')][0]
            d = {chan_coords : chan}
            arr = arr.sel(**d)
        times = arr.coords[time_coords].values
        sig = arr.values
        return sig, times



class DataFromCns:
    def __init__(self, reader):
        self.reader = reader
        self.prefered_dtype = np.dtype('datetime64[us]')
        self.events = reader.events

    def get_stream_names(self):
        return list(self.reader.streams.keys())

    def get_start_stop(self, stream_names):
        start = min([self.reader.streams[name].get_times()[0] for name in stream_names])
        stop = max([self.reader.streams[name].get_times()[-1] for name in stream_names])
        return start, stop

    def get_channels(self, stream_names):
        channels =[]
        for stream_name, stream in self.reader.streams.items():
            if stream_names is not None and stream_name not in stream_names:
                continue
            if stream.channel_names is None:
                channels.append(stream_name)
            else:
                channels.extend([f'{stream_name}/{chan}' for chan in stream.channel_names])        
        return channels

    def get_units(self, stream_name):
        return self.reader.streams[stream_name].units

    def get_signal(self, stream_name, chan, t0, t1):
        stream = self.reader.streams[stream_name]
        sig, times = stream.get_data(sel=slice(t0, t1), with_times=True, apply_gain=True)
        if chan is not None:
            chan_ind = list(stream.channel_names).index(chan)
            sig = sig[:, chan_ind]
        return sig, times


class TimeSlider(W.HBox):

    time_range_int = traitlets.Tuple(traitlets.Int(), traitlets.Int())
    
    def __init__(self, start, stop, **kwargs):
        
        time_range = [start, start + np.timedelta64(300, 's')]
        
        self.start = start
        self.stop = stop
        self.dtype = start.dtype
        self.start_int = self.start.view(np.int64)
        self.stop_int = self.stop.view(np.int64)
        
        
        self.time_range_int = (int(time_range[0].view(np.int64)), int(time_range[1].view(np.int64)))
        self.observe(self.on_time_range_int_changed, names=['time_range_int'], type='change')
        
        
        layout = W.Layout(align_items="center", width="1.5cm", height="100%")
        but_left = W.Button(description='', disabled=False, button_style='', icon='arrow-left', layout=layout)
        but_right = W.Button(description='', disabled=False, button_style='', icon='arrow-right', layout=layout)
        
        but_left.on_click(self.move_left)
        but_right.on_click(self.move_right)

        self.move_size = W.Dropdown(options=['1 s', '1 m', '30 m', '1 h', '6 h', '24 h'],
                                    value='1 h',
                                    description='',
                                    layout = W.Layout(width="2cm")
                                    )

        # DatetimePicker is only for ipywidget v8 (which is not working in vscode 2023-03)
        self.time_label = W.Text(value=f'{time_range[0]}',description='',
                                 disabled=False, layout=W.Layout(width='5.5cm'))
        self.time_label.observe(self.time_label_changed)


        self.slider = W.IntSlider(
            orientation='horizontal',
            # description='time:',
            value=self.start_int,
            min=self.start_int,
            max=self.stop_int,
            readout=False,
            continuous_update=False,
            layout=W.Layout(width=f'70%')
        )
        
        self.slider.observe(self.slider_moved)
        
        delta_s = (time_range[1] - time_range[0]).astype("timedelta64[s]").view(int)
        
        self.window_sizer = W.BoundedFloatText(value=delta_s, step=60, min=1,max= 360000,
                                        description='win (s)',
                                        layout=W.Layout(width='auto')
                                        # layout=W.Layout(width=f'10%')
                                        )
        self.window_sizer.observe(self.win_size_changed)
        
        

        super(W.HBox, self).__init__(children=[but_left, self.move_size, but_right, self.slider, self.time_label, self.window_sizer],
                                     layout=W.Layout(align_items="center", width="100%", height="100%"),
                                     **kwargs)
    def get_time_range(self):
        t0 = np.int64(self.time_range_int[0]).view(self.dtype)
        t1 = np.int64(self.time_range_int[1]).view(self.dtype)
        return t0, t1
    
    def update_time(self, new_time=None, delta_s=None, update_slider=False, update_label=False):

        if new_time is None:
            # t0 = np.int64(self.slider.value).view(self.dtype)
            t0 = np.int64(self.time_range_int[0]).view(self.dtype)
        else:
            t0 = new_time.astype(self.dtype)
        
        if delta_s is None:
            delta_s = self.window_sizer.value
        t1 = (t0 + np.timedelta64(int(delta_s), 's')).astype(self.dtype)
        
        self.time_range_int = (int(t0.view(np.int64)), int(t1.view(np.int64)))

        if update_label:
            self.time_label.unobserve(self.time_label_changed)
            self.time_label.value = f'{t0}'
            self.time_label.observe(self.time_label_changed)

        if update_slider:
            self.window_sizer.unobserve(self.win_size_changed)
            self.slider.value = int(t0.view('int64'))
            self.window_sizer.observe(self.win_size_changed)

    def on_time_range_int_changed(self, change=None):
        self.update_time( update_slider=True, update_label=True)
        

    def time_label_changed(self, change=None):
        try:
            new_time = np.datetime64(self.time_label.value).view(self.dtype)
        except:
            new_time = None

        if new_time is not None:
            self.update_time(new_time=new_time, update_slider=True)

    def win_size_changed(self, change=None):
        delta_s = self.window_sizer.value
        self.update_time(delta_s=delta_s)
        
    def slider_moved(self, change=None):
        new_time = np.int64(self.slider.value).view(self.dtype)
        self.update_time(new_time=new_time, update_label=True)
    
    def move(self, sign):
        value, units = self.move_size.value.split(' ')
        value = int(value)
        delta = sign * np.timedelta64(value, units)
        new_time = np.int64(self.time_range_int[0]).view(self.dtype) + delta
        self.slider.value = int(new_time.view('int64'))
    
    def move_left(self, change=None):
        self.move(-1)

    def move_right(self, change=None):
        self.move(+1)


                                 

def make_channel_selector(data, stream_names, ext_plots, width_cm=10, height_cm=5):
    channels = data.get_channels(stream_names)

    if ext_plots is not None:
        channels.extend([name for name in ext_plots.keys()])

    
    chan_selected = channels[:6]
    
    channel_selector = W.SelectMultiple(
        options=channels,
        value=chan_selected,
        disabled=False,
        layout=W.Layout(width=f'{width_cm}cm', height=f'{height_cm}cm')
    )
    
    some_widgets = {'channel_selector': channel_selector}
    return channel_selector, some_widgets


class EventSelector(W.VBox):
    index = traitlets.Int()

    def __init__(self, events, **kwargs):
        self.events = events

        event_list = []
        for i in range(self.events['start_time'].size):
            start_time = self.events['start_time'][i].astype(datetime.datetime)
            name = self.events['name'][i]
            start_time_txt = start_time.strftime("%Y-%m-%d %H:%M:%S")
            event_list.append(f"{start_time_txt} {name}")


        self.selector = W.Select(
            options=event_list,
            value=None,
            disabled=False,
            layout=W.Layout(height="100%", width="12cm"),
        )

        super(W.VBox, self).__init__(
            children=[self.selector],
            layout=W.Layout(align_items="center"),
            **kwargs,
        )
    
        self.selector.observe(self.on_index_changed, names=['index'], type='change')

    def on_index_changed(self, change=None):
        self.index = self.selector.index




class Viewer(W.Tab):
    def __init__(self, data_in, stream_names, ext_plots=None, with_events=True):
        
        if isinstance(data_in, xr.Dataset):
            self.data = DataFromXarray(data_in)
        elif isinstance(data_in, CnsReader):
            self.data = DataFromCns(data_in)
        else:
            raise ValueError(f'Viewer get wrong data {data_in}')

        if with_events and self.data.events is not None:
            self.event_selector = EventSelector(self.data.events)
            self.event_selector.observe(self.on_event_changed, names='index', type='change')

        else:
            self.event_selector = None

        if stream_names is None:
            stream_names = self.data.get_stream_names()
        
        if ext_plots is not None:
            # TODO check that this do not overlap with channel names
            # channels = data.get_channels(stream_names)
            if isinstance(ext_plots, list):
                self.ext_plots = {p.name: p for p in ext_plots}
            else:
                self.ext_plots = ext_plots
        else:
            self.ext_plots = {}
        
        # TODO force canvas to ipympl
        
        # this trick prevent the figure to be displayed in jupyter directly
        # mpl_output = W.Output(layout={'border': '1px solid black'})
        mpl_output = W.Output()
        with plt.ioff():
            with mpl_output:
                # self.fig = plt.figure(constrained_layout=True, )  # figsize=(14, 10)
                self.fig = plt.figure(constrained_layout=False, )
                canvas = self.fig.canvas
                # self.canvas = canvas
                canvas.toolbar_visible = True
                canvas.header_visible = False
                canvas.footer_visible = False
                # canvas.resizable = False
                # canvas.resizable = True
                # canvas.max_width = '2800px'
                # canvas.layout.min_height = '200px'
                # canvas.layout.min_width = '400px'
                # canvas.layout.width = '100%'
                # canvas.capture_scroll = False
                self.axs = None
                plt.show()
        # print(canvas)
        # with plt.ioff():
        #         # self.fig = plt.figure(constrained_layout=True, )  # figsize=(14, 10)
        #         self.fig = plt.figure(constrained_layout=False, figsize=None )
        #         canvas = self.fig.canvas
        #         # self.canvas = canvas
        #         canvas.toolbar_visible = False
        #         canvas.header_visible = False
        #         canvas.footer_visible = False
        #         # canvas.resizable = False
        #         canvas.resizable = True
        #         # canvas.max_width = '2800px'
        #         # canvas.layout.min_height = '200px'
        #         # canvas.layout.min_width = '400px'
        #         canvas.layout.width = '100%'
        #         # canvas.capture_scroll = False
        #         self.axs = None
        #         plt.show()

        start, stop = self.data.get_start_stop(stream_names)
        self.time_slider = TimeSlider(start, stop)

        self.channel_selector, some_widgets=make_channel_selector(self.data, stream_names, self.ext_plots)
        
        
        self.time_slider.observe(self.refresh)
        self.channel_selector.observe(self.full_refresh)
        
        but_refresh = W.Button(description='autoscale', disabled=False, icon='refresh')
        but_refresh.on_click(self.auto_scale)
        if self.event_selector is not None:
            tools = W.HBox([but_refresh, self.event_selector,])
        else:
            tools = W.HBox([but_refresh])
        tab0 = W.VBox([tools, self.fig.canvas, self.time_slider])

            
        # tab0 = W.VBox([mpl_output, self.time_slider])
        
        tab1 = W.VBox([self.channel_selector])
        super(W.Tab, self).__init__(children=[tab0, tab1], layout=W.Layout(width='100%'))
        self.set_title(0, 'main')
        self.set_title(1, 'options')

        
        canvas.layout.width = '100%'
        # mpl_output.layout.width = '100%'
        
        self.full_refresh()
    
    def get_visible_channels(self):
        channels = []
        for k in self.channel_selector.value:
            if '/' in k:
                stream_name, chan = k.split('/')
            else:
                stream_name, chan = k, None
            channels.append([stream_name, chan])
        return channels
    
    def reset_axes(self):

        channels = self.get_visible_channels()
        self.fig.clear()
        n = len(channels)
        gs = self.fig.add_gridspec(nrows=n, ncols=1,
                                   left=0.15, right=.95, top=1., bottom=0.1,
                                   hspace=0)
        
        # self.axs = [self.fig.add_subplot(gs[i]) for i in range(n)]
        self.axs = []
        for i in range(n):
            channel = channels[i]
            stream_name, chan = channel

            ax = self.fig.add_subplot(gs[i])

            if stream_name not in self.ext_plots:
                
                if chan is None:
                    label = stream_name
                else:
                    label = chan
                units = self.data.get_units(stream_name)
                if units is not None:
                    label = label + f'\n[{units}]'
            else:
                label = stream_name

            ax.set_ylabel(label)
            self.axs.append(ax)
        
        for ax in self.axs[:-1]:
            ax.sharex(self.axs[-1])
            ax.tick_params(labelbottom=False)
    
    def full_refresh(self,  change=None):
        self.reset_axes()
        self.refresh()
    
    def refresh(self, change=None, autoscale=False,):
        if self.axs is None:
            self.reset_axes()
        
        t0, t1 = self.time_slider.get_time_range()
        channels = self.get_visible_channels()
        
        for i, channel in enumerate(channels):
            # TODO change the channel concept
            # this approach is not optimal because several call to the same stream when EEG
            
            ax = self.axs[i]
            
            for l in ax.lines:
                # clear remove also labels
                l.remove()
            
            stream_name, chan = channels[i]
            if stream_name not in self.ext_plots:
                sig, times = self.data.get_signal(stream_name, chan, t0, t1)
                ax.plot(times, sig, color='k')
                if autoscale:
                    # a clear is enough to make matplotlib make new ylim
                    ax.relim()
                    ax.autoscale_view(scalex=False, scaley=True)
            else:
                self.ext_plots[stream_name].plot(ax, t0, t1)



        # set scale on last axis
        ax = self.axs[-1]
        ax.set_xlim(t0, t1)


        

        self.fig.canvas.draw()
        # self.fig.canvas.flush_events()

    def auto_scale(self, change=None,):
        self.refresh(autoscale=True)
    
    def on_event_changed(self, change=None,):
        ind = self.event_selector.index
        if ind is None:
            return
        delta = self.time_slider.time_range_int[1] - self.time_slider.time_range_int[0]
        start_time_int = int(self.data.events['start_time'].view('int64')[ind])
        self.time_slider.time_range_int = (start_time_int - delta //2, start_time_int+delta // 2)

    

def get_viewer(*args, **kwargs):
    return Viewer(*args, **kwargs)

