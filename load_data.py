import xlrd, os
import numpy as np
from scipy.io import loadmat
import pickle


labels_file_path = os.path.join(os.path.dirname(__file__), "Succ_Unsucc_runs.xlsx")
labels_file_content = xlrd.open_workbook(labels_file_path)
dataset_path = "/Users/gokcengokceoglu/Desktop/erbilpreprocessed_tol/downsampled_normalized"
full_dataset = []
succ_labels = []

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
    if success_label == 's':
        full_dataset.append(subject_session_data['data'])
        succ_labels.append(1)
    else :
        full_dataset.append(subject_session_data['data'])
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

    with open('sess_info.pickle', 'wb') as f:
        pickle.dump(sess_info, f)

    a = 3
