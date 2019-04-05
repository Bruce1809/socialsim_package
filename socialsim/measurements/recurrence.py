
import sys
import numpy as np
import pandas as pd
from scipy.stats.stats import pearsonr
import burst_detection as bd
import os
from .measurements import MeasurementsBaseClass
from ..utils import get_community_contentids

class ContentRecurrenceMeasurements(MeasurementsBaseClass):
    def __init__(self, dataset_df, configuration={}, 
        id_col='nodeID', timestamp_col="nodeTime", 
        userid_col="nodeUserID", platform_col="platform", 
        content_col="informationID", communities=None, 
        log_file='recurrence_measurements_log.txt', content_id=None, 
        time_granularity='D'):
        """
        :param dataset_df: dataframe containing all posts for a single coin in all platforms
        :param timestamp_col: name of the column containing the time of the post
        :param id_col: name of the column containing the post id
        :param userid_col: name of the column containing the user id
        :param content_col: name of the column containing the content the simulation was done for eg. coin name
        """
        super(ContentRecurrenceMeasurements, self).__init__(
            dataset_df, configuration, log_file=log_file)
        self.dataset_df = dataset_df
        self.community_set = communities
        self.timestamp_col = timestamp_col
        self.id_col = id_col
        self.userid_col = userid_col
        self.platform_col = platform_col
        self.content_col = content_col
        self.measurement_type = 'recurrence'
        self.content_id = content_id
        self.time_granularity = time_granularity
        self.get_per_epoch_counts()
        self.detect_bursts()
        self._time_between_bursts_distribution = None

    def get_per_epoch_counts(self):
        '''
        group activity by provided time granularity and get size and unique user counts per epoch
        time_granularity: s, Min, 10Min, 30Min, H, D, ...
        '''
        self.dataset_df.loc[:,self.timestamp_col] = pd.to_datetime(self.dataset_df[self.timestamp_col])
        self.counts_df = self.dataset_df.set_index(self.timestamp_col).groupby(pd.Grouper(
            freq=self.time_granularity))[[self.id_col, self.userid_col]].nunique().reset_index()

    def detect_bursts(self, s=2, gamma=0.3):
        '''
        detect intervals with bursts of activity: [begin_timestamp, end_timestamp)
        :param s: multiplicative distance between states (input to burst_detection library)
        :param gamma: difficulty associated with moving up a state (input to burst_detection library)
        burst_detection library: https://pypi.org/project/burst_detection/
       '''
        if len(self.dataset_df) < 2:
            self.burst_intervals = None
            return
        r = self.counts_df[self.id_col].values
        n = len(r)
        d = np.array([sum(r)] * n, dtype=float)
        q = bd.burst_detection(r, d, n, s, gamma, 1)[0]
        bursts_df = bd.enumerate_bursts(q, 'burstLabel')
        index_date = pd.Series(
            self.counts_df[self.timestamp_col].values, index=self.counts_df.index).to_dict()
        bursts_df['begin_timestamp'] = bursts_df['begin'].map(index_date)
        bursts_df['end_timestamp'] = bursts_df['end'].map(index_date)
        time_granularity = index_date[1] - index_date[0]
        self.burst_intervals = [(burst['begin_timestamp'], burst['end_timestamp'] +
                                 time_granularity) for _, burst in bursts_df.iterrows()]
        # print('number of bursts: ', len(self.burst_intervals))
        # print(self.dataset_df[[self.timestamp_col]].sort_values(self.timestamp_col))
        self.update_with_burst()

    def update_with_burst(self):
        '''update dataset_df with burst index'''
        self.dataset_df['burst_index'] = None
        if self.burst_intervals is None:
            self.grouped_bursts = None
            return
        for idx, burst_interval in enumerate(self.burst_intervals):
            self.dataset_df.loc[self.dataset_df[self.timestamp_col].between(
                burst_interval[0], burst_interval[1], inclusive=False), 'burst_index'] = idx

        if 'burst_index' in self.dataset_df:
            self.grouped_bursts = self.dataset_df.dropna(subset=['burst_index']).groupby('burst_index')

    @property
    def time_between_bursts_distribution(self):
        if self._time_between_bursts_distribution is None:
            self._time_between_bursts_distribution = [(start_j - end_i).total_seconds() / (60*60*24) for (_, end_i), (start_j, _) in zip(self.burst_intervals[:-1], self.burst_intervals[1:])]
        return self._time_between_bursts_distribution


    def number_of_bursts(self):
        '''
        How many renewed bursts of activity are there?
        '''
        return len(self.burst_intervals)

    def time_between_bursts(self):
        '''
        How much time elapses between renewed bursts of activity on average?
        Time granularity: days
        '''
        return np.mean(self.time_between_bursts_distribution)

    def average_size_of_each_burst(self):
        '''
        How many times is the information shared per burst on average?
        '''
        return self.grouped_bursts.size().reset_index(name='size')['size'].mean()

    def average_number_of_users_per_burst(self):
        '''
        How many users are reached by the information during each burst on average?
        '''
        return self.grouped_bursts[[self.userid_col]].nunique().reset_index()[self.userid_col].mean()

    def burstiness_of_burst_timing(self):
        '''Do multiple bursts of renewed activity tend to cluster together?'''
        std = np.std(self.time_between_bursts_distribution)
        mean = np.mean(self.time_between_bursts_distribution)
        return (std - mean) / (std + mean) if std + mean > 0 else 0

    def new_users_per_burst(self):
        '''
        How many new users are reached by the information during each burst on average?
        First burst is also counted.
        '''
        users = set()
        num_new_users = []
        for _, single_burst_df in self.grouped_bursts:
            old_len = len(users)
            users.update(single_burst_df[self.userid_col].unique())
            num_new_users.append(len(users) - old_len)
        return np.mean(num_new_users)

    def lifetime_of_each_burst(self):
        '''
        How long does each burst last on average?
        Time granularity: minutes
        '''
        return np.mean([(end_i - start_i).total_seconds() / 60 for (start_i, end_i) in self.burst_intervals])

    def average_proportion_of_top_platform_per_burst(self):
        '''
        Do individual bursts tend to occur on a single platform or are they distributed among platforms?
        '''
        return np.mean([single_burst_df[self.platform_col].value_counts().max()/len(single_burst_df) for _, single_burst_df in self.grouped_bursts])


class RecurrenceMeasurements(MeasurementsBaseClass):
    def __init__(self, dataset_df, configuration={}, metadata=None,
    id_col='id_h', timestamp_col="nodeTime", userid_col="nodeUserID", platform_col="platform", content_col="informationID", communities=None, log_file='recurrence_measurements_log.txt', selected_content=None, selected_communties=None, time_granularity='D'):
        """
        :param dataset_df: dataframe containing all posts for all communities (Eg. coins for scenario 2) in all platforms
        :param timestamp_col: name of the column containing the time of the post
        :param id_col: name of the column containing the post id
        :param userid_col: name of the column containing the user id
        :param content_col: name of the column containing the content the simulation was done for eg. coin name
        """
        super(RecurrenceMeasurements, self).__init__(dataset_df, configuration, log_file=log_file)
        self.dataset_df          = dataset_df
        self.community_set       = communities
        self.timestamp_col       = timestamp_col
        self.id_col              = id_col
        self.userid_col          = userid_col
        self.platform_col        = platform_col
        self.content_col = content_col
        self.measurement_type    = 'recurrence'
        self.metadata            = metadata 
        self.selected_content    = selected_content
        self.selected_communties = selected_communties
        self.community_contentids = None
        self.time_granularity = time_granularity
        if self.metadata is not None:
            self.community_contentids = get_community_contentids(self.metadata.community_directory)
        self.initialize_recurrence_measurements()

    def initialize_recurrence_measurements(self):
        self.content_recurrence_measurements = {}
        for content_id, content_df in self.dataset_df.groupby(self.content_col):
            self.content_recurrence_measurements[content_id] = ContentRecurrenceMeasurements(dataset_df=content_df, id_col=self.id_col, timestamp_col=self.timestamp_col, userid_col=self.userid_col, platform_col=self.platform_col, content_col=self.content_col, configuration=self.configuration, content_id=content_id, time_granularity=self.time_granularity)

    def run_content_level_measurement(self, measurement_name, scale='node',
                selected_content=None):
        selected_content = next(x for x in [selected_content, self.selected_content, self.content_recurrence_measurements.keys()] if x is not None)
        contentid_value = {content_id: getattr(self.content_recurrence_measurements[content_id], measurement_name)() for content_id in selected_content}
        if scale == 'node':
            return contentid_value
        elif scale == 'population':
            return pd.DataFrame(list(contentid_value.items()), columns=[self.content_col, 'value'])

    def run_community_level_measurement(self, measurement_name, selected_communties=None):
        if self.community_contentids is None:
            print('No communities provided')
            return
        selected_communties = next(x for x in [selected_communties, self.selected_communties, self.community_contentids.keys()] if x is not None)
        return {community: pd.DataFrame(list(self.run_content_level_measurement(measurement_name, 
                selected_content=self.community_contentids[community]).items()), columns=[self.content_col, 'value']) for community in selected_communties}

