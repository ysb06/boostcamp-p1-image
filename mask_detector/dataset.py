from enum import Enum
from typing import Any, List, Tuple
import random

import albumentations as A
import cv2 as cv
import pandas as pd
from albumentations.augmentations import SmallestMaxSize
from albumentations.pytorch import ToTensorV2
from glob import glob
from pandas.core.series import Series
from torch import LongTensor, Tensor
from torch.utils.data import Dataset
from torchvision import transforms
from tqdm import tqdm


class Gender(Enum):
    Male = 0
    Female = 1

class DatasetType(Enum):
    General = 0
    Mask_Weared = 1
    Correct_Mask = 2
    Gender = 3
    Under30Age = 4
    Over59Age = 5


class PersonLabel():
    def __init__(self) -> None:
        self.mask_exist: bool = False
        self.correct_mask: bool = False
        self.gender: Gender = Gender.Male
        self.age: int = 0

    def get_combined_label(self) -> int:
        label = 0
        if not self.correct_mask:
            label = 6

        if not self.mask_exist:
            label = 12

        label += self.gender.value * 3 + self.get_age_label().item()

        return LongTensor([label])

    def get_mask_exist_label(self) -> LongTensor:
        return LongTensor([self.mask_exist])

    def get_correct_mask_label(self) -> LongTensor:
        return LongTensor([self.correct_mask])

    def get_gender_label(self) -> LongTensor:
        return LongTensor([self.gender.value])

    def get_age_label(self) -> LongTensor:
        if self.age < 30:
            return LongTensor([0])
        elif self.age > 59:
            return LongTensor([2])
        else:
            return LongTensor([1])

    def get_under30_label(self) -> LongTensor:
        return LongTensor([int(self.age < 30)])

    def get_over59_label(self) -> LongTensor:
        return LongTensor([int(self.age > 59)])
    
    def get_label(self, label_type: DatasetType) -> LongTensor:
        label: LongTensor = None
        if label_type == DatasetType.Mask_Weared:
            label = self.get_mask_exist_label()
        elif label_type == DatasetType.Correct_Mask:
            label = self.get_correct_mask_label()
        elif label_type == DatasetType.Gender:
            label = self.get_gender_label()
        elif label_type == DatasetType.Under30Age:
            label = self.get_under30_label()
        elif label_type == DatasetType.Over59Age:
            label = self.get_correct_mask_label()
        else:
            label = self.get_combined_label()
        
        return label

# 레이블 제공을 유연하게 할 수 있는 방법이 있을까?
# Dict로 구성하고 Key를 받는 방식이면 가능했을 듯.
# 다만, string key로 받는 방식을 좋아하지 않아(애매해짐 Vague) 그렇게 하지는 않음


class Person():
    def __init__(self) -> None:
        self.image_path: str = ""
        self.image_raw: Any = None
        self.label: PersonLabel = PersonLabel()


class MaskedFaceDataset(Dataset):
    def __init__(self) -> None:
        self.data: List[Person] = []
        self.transform: transforms.Compose = None
        self.serve_type = DatasetType.General
        self.serve_list = []

    def __len__(self):
        return len(self.serve_list)

    def __getitem__(self, index) -> Tensor:
        target: Person = self.data[self.serve_list[index]]

        source = self.transform(image=target.image_raw)["image"]
        label = target.label.get_label(self.serve_type)

        # 혹시 Data를 Load했을 때 3번째 부분이 문제가 될 수 있으므로 테스트 필요
        return source, label, target.image_path

    def generate_serve_list(self, serve_type: DatasetType, shuffle: bool = False, random_seed: int = None):
        self.serve_type = serve_type
        # 레이블 데이터를 Class List가 아닌 그냥 Pandas로 저장했으면 훨씬 더 좋았을 것 같음
        # 그러면 pandas가 제공하는 기능을 그대로 쓸 수 있었을 텐데...

        rnd = random.Random(random_seed)
        lesser_class_group = []
        greater_class_group = []
        # Oversampling
        
        # 갑자기 든 생각이지만 성별, 나이 구분도 마스크 여부에 따라 달라지지 않을까?
        # 하지만 이것저것 다 고려하면 머리 터질 것 같아 더 이상 생각하지 않음
        for index, data in enumerate(self.data):
            # 하위 수준 모델(마스크 제대로 썼는지, 60이상인지)에서 들어오는 데이터는 정확할 것이라고 판단.
            if serve_type == DatasetType.Mask_Weared:
                # 마스크를 쓴 데이터가 적은 데이터이다 (2:5)
                if data.label.mask_exist == True:
                    lesser_class_group.append(index)
                else:
                    greater_class_group.append(index)
            elif serve_type == DatasetType.Correct_Mask:
                # 마스크를 잘못 쓴 데이터가 적은 데이터이다 (1:5)
                if data.label.mask_exist == True:   # 마스크가 없는 데이터는 아예 넣지 않음
                    if data.label.correct_mask == True:
                        lesser_class_group.append(index)
                    else:
                        greater_class_group.append(index)
            elif serve_type == DatasetType.Gender:
                # 남자가 더 적은 데이터이다
                if data.label.gender == Gender.Male:
                    lesser_class_group.append(index)
                else:
                    greater_class_group.append(index)
            elif serve_type == DatasetType.Under30Age:
                # 남자가 더 적은 데이터이다
                if data.label.age < 30:
                    lesser_class_group.append(index)
                else:
                    greater_class_group.append(index)
            elif serve_type == DatasetType.Over59Age:
                if data.label.age > 59:
                    lesser_class_group.append(index)
                else:
                    greater_class_group.append(index)
            else:
                self.serve_list = [*range(len(self.data))]
                return  
                # 알 수 없는 데이터셋 형식은 원래 데이터 그대로 나오도록 처리
        
        if shuffle:
            rnd.shuffle(lesser_class_group)
            rnd.shuffle(greater_class_group)
        
        if len(lesser_class_group) > len(greater_class_group):
            raise Exception("Dividing code error")

        while len(lesser_class_group) * 2 < len(greater_class_group):
            lesser_class_group *= 2
        lesser_class_group += lesser_class_group[:(len(greater_class_group) - len(lesser_class_group))]

        if len(lesser_class_group) != len(greater_class_group):
            raise Exception("Oversampling code error")
        
        self.serve_list = greater_class_group + lesser_class_group
        if shuffle:
            rnd.shuffle(self.serve_list)
        

def get_basic_train_transforms(
        image_size: Tuple[int, int], 
        mean: Tuple[float, float, float] = (0.548, 0.504, 0.479), 
        std: Tuple[float, float, float] = (0.237, 0.247, 0.246)
    ):
    min_length = min(image_size[0], image_size[1])
    train_transforms = A.Compose([
        SmallestMaxSize(max_size=min_length, always_apply=True),
        A.CenterCrop(min_length, min_length, always_apply=True),
        A.Resize(image_size[0], image_size[1], p=1.0),
        A.HorizontalFlip(p=0.5),
        A.ShiftScaleRotate(p=0.5),
        A.HueSaturationValue(hue_shift_limit=0.2,
                             sat_shift_limit=0.2, 
                             val_shift_limit=0.2, 
                             p=0.5),
        A.RandomBrightnessContrast(
            brightness_limit=(-0.1, 0.1), 
            contrast_limit=(-0.1, 0.1), 
            p=0.5),
        A.GaussNoise(p=0.5),
        A.Normalize(mean=mean, std=std, max_pixel_value=255.0, p=1.0),
        ToTensorV2(p=1.0),
    ])

    return train_transforms


def get_valid_transforms(
        image_size: Tuple[int, int], 
        mean: Tuple[float, float, float] = (0.548, 0.504, 0.479), 
        std: Tuple[float, float, float] = (0.237, 0.247, 0.246)
    ):
    val_transforms = A.Compose([
        A.Resize(image_size[0], image_size[1], p=1.0),
        A.Normalize(mean=mean, std=std, max_pixel_value=255.0, p=1.0),
        ToTensorV2(p=1.0),
    ])

    return val_transforms


def generate_train_datasets(
    data_root_path: str,
    random_seed: int = None,
    validation_ratio: int = 0.25,   # 추후 Validation 구현할 것
):
    """학습 데이터셋 생성

    Args:
        data_root_path (str): eval과 train폴더가 들어있는 폴더
        random_seed (int, optional): 학습 데이터셋과 검증 데이터셋으로 나누기 전 랜덤으로 섞을 때 사용하는 시드 값. 기본은 None이며 이 경우 랜덤으로 섞지 않음.
        validation_ratio (int, optional): 검증 데이터 셋 비율. 기본은 일반적으로 사용되는 6:2:2에 해당하는 값
    """
    image_path = f"{data_root_path}/train/images"
    label_raw = pd.read_csv(f"{data_root_path}/train/train.csv")
    if random_seed is not None:
        label_raw = label_raw.sample(frac=1, random_state=random_seed)
        label_raw = label_raw.reset_index(drop=True)

    # train, valid Dataframe으로 나누는 작업
    valid_size = int(len(label_raw) * validation_ratio)

    valid_label_raw = label_raw.iloc[:valid_size + 1]
    train_label_raw = label_raw.iloc[valid_size + 1:]
    # 원래는 60세 이상의 데이터 갯수가 부족하면 채워넣도록 코드를 짜려고 했지만 
    # 생각보다 원하는 비율로 잘 맞춰지고 있어서 일단 유보

    # 60 이상 분류가 잘 되지 않을 경우 수정할 것
    # count_60 = len(valid_label_raw[valid_label_raw["age"] > 59])
    # min_count_60 = int(192 * validation_ratio)

    train_label_raw.reset_index(drop=True)
    valid_label_raw.reset_index(drop=True)

    # Train Dataset 생성
    train_dataset = MaskedFaceDataset()
    train_dataset.transform = get_basic_train_transforms((128, 128))

    for label_data in tqdm(train_label_raw.iloc, total=len(train_label_raw)):
        target_image_dir = image_path + '/' + label_data["path"] + '/'
        gender = Gender.Male if label_data["gender"] == "male" else Gender.Female
        age = int(label_data["age"])

        inc_mask_image_path = glob(target_image_dir + "incorrect_mask.*")[0]
        mask_images_path = glob(target_image_dir + "mask*")
        normal_image_path = glob(target_image_dir + "normal.*")[0]

        __add_data_to_dataset(train_dataset,  inc_mask_image_path, gender, age, True, False)
        for mask_image_path in mask_images_path:
            __add_data_to_dataset(train_dataset,  mask_image_path, gender, age, True, True)
        __add_data_to_dataset(train_dataset,  normal_image_path, gender, age, False, False)

    # Validation Dataset 생성
    valid_dataset = MaskedFaceDataset()
    valid_dataset.transform = get_valid_transforms((128, 128))

    for label_data in tqdm(valid_label_raw.iloc, total=len(valid_label_raw)):
        target_image_dir = image_path + '/' + label_data["path"] + '/'
        gender = Gender.Male if label_data["gender"] == "male" else Gender.Female
        age = int(label_data["age"])

        inc_mask_image_path = glob(target_image_dir + "incorrect_mask.*")[0]
        mask_images_path = glob(target_image_dir + "mask*")
        normal_image_path = glob(target_image_dir + "normal.*")[0]

        __add_data_to_dataset(valid_dataset,  inc_mask_image_path, gender, age, True, False)
        for mask_image_path in mask_images_path:
            __add_data_to_dataset(valid_dataset,  mask_image_path, gender, age, True, True)
        __add_data_to_dataset(valid_dataset,  normal_image_path, gender, age, False, False)

    train_dataset.generate_serve_list(DatasetType.General)
    valid_dataset.generate_serve_list(DatasetType.General)
    return train_dataset, valid_dataset


def __add_data_to_dataset(
    dataset: MaskedFaceDataset,
    image_path: str,
    gender: int,
    age: int,
    mask_weared: bool,
    mask_in_good_condition: bool
):
    image = cv.imread(image_path)
    image = cv.cvtColor(image, cv.COLOR_BGR2RGB)

    data = Person()
    data.image_path = image_path
    data.image_raw = image
    data.label.gender = gender
    data.label.age = age
    data.label.mask_exist = mask_weared
    data.label.correct_mask = mask_in_good_condition

    dataset.data.append(data)

    # 데이터셋에 데이터를 넣는 코드
