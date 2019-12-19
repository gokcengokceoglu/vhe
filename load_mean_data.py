import xlrd, os
import numpy as np
from scipy.io import loadmat
import pickle


labels_file_path = os.path.join(os.path.dirname(__file__), "Succ_Unsucc_runs.xlsx")
labels_file_content = xlrd.open_workbook(labels_file_path)
dataset_path = "/Users/gokcengokceoglu/Desktop/erbilpreprocessed_tol/downsampled_normalized"
full_dataset = []
succ_labels = []
max_region_idx = 107

def loadMatFile(file_path):
    subject = os.path.split(os.path.dirname(file_path))[1]
    session = os.path.split(file_path)[1][len("sess"):os.path.split(file_path)[1].find('.')]

    row_idx = [row for     row in range(labels_file_content.sheet_by_name("labels").nrows) if subject+"-"+session
               in str(labels_file_content.sheet_by_name("labels").cell(row, 0))][0]
    labels = [int(cell.value) for cell in [labels_file_content.sheet_by_name("labels").cell(row_idx, x) for x in range(1,591)]]
    success_label = labels_file_content.sheet_by_name("labels").cell(row_idx, 593).value

    subject_session_data = loadmat(file_path)
    subject_session_data['labels'] = np.array(labels)
    subject_session_data['success_label'] = success_label
    subject_session_data['meta'] = [subject, session]
    new_sample = np.zeros((590,89))
    if success_label == 's':
        subj_recording = np.array(subject_session_data['data'])
        regionIds = subject_session_data['regionIDs']
        reqionIds_unique = np.unique(regionIds)
        # Take the mean values of recordings for each regionId :
        for ii in range(len(reqionIds_unique)):
            for time_instance in range(590):
                region_idx = reqionIds_unique[ii]
                curr_regions_list = np.where(regionIds == region_idx)[0]
                curr_regions_list = np.subtract(curr_regions_list,1)
                subj_recording_time_instance = subj_recording[:, time_instance]
                region_measurings = subj_recording_time_instance[curr_regions_list]
                mean_region_measurings = np.median(region_measurings, axis=0)
                new_sample[time_instance][ii] = mean_region_measurings
            print(region_idx)

        full_dataset.append(new_sample)
        succ_labels.append(1)
    else :
        subj_recording = np.array(subject_session_data['data'])
        regionIds = subject_session_data['regionIDs']
        reqionIds_unique = np.unique(regionIds)
        # Take the mean values of recordings for each regionId :
        for ii in range(len(reqionIds_unique)):
            for time_instance in range(590):
                region_idx = reqionIds_unique[ii]
                curr_regions_list = np.where(regionIds == region_idx)[0]
                curr_regions_list = np.subtract(curr_regions_list,1)
                subj_recording_time_instance = subj_recording[:, time_instance]
                region_measurings = subj_recording_time_instance[curr_regions_list]
                mean_region_measurings = np.median(region_measurings, axis=0)
                new_sample[time_instance][ii] = mean_region_measurings
            print(region_idx)

        full_dataset.append(new_sample)
        succ_labels.append(0)
    return full_dataset, succ_labels



if __name__ == '__main__':
    subject_directories = [os.path.join(dataset_path, subject_dir) for subject_dir in os.listdir(dataset_path) \
                           if os.path.isdir(os.path.join(dataset_path, subject_dir))]
    session_paths = map(lambda a:[os.path.join(a, x) for x in os.listdir(a)], subject_directories)

    data = list()
    for subject in session_paths:
        for session in subject:
            sess_info = loadMatFile(session)

    with open('sess_info_median_by_region_ids.pickle', 'wb') as f:
        pickle.dump(sess_info, f)

    a = 3
