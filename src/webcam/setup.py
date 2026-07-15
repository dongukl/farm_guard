from setuptools import find_packages, setup

package_name = 'webcam'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['ground_homography.npy', 'best.pt']},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='donguk',
    maintainer_email='ouk279952@gmail.com',
    description='Tower webcam perception: YOLO detection, ByteTrack, and homography calibration',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'tower_world_detector = webcam.tower_world_detector:main',
            'calibrate_homography = webcam.calibrate_homography:main',
        ],
    },
)
